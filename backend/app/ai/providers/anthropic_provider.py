import logging
import os
from typing import Any, AsyncIterator

import anthropic
import instructor
from pydantic import BaseModel

from app.ai.providers.base import (
    LLMProvider,
    Message,
    ModelInfo,
    LLMProviderError,
    ToolCallRequest,
    ToolChatResult,
)
from app.ai.providers.errors import attach_reset_marker, extract_reset_at

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Anthropic Claude provider."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        timeout: float = 120.0,
    ):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMProviderError(
                "ANTHROPIC_API_KEY not set. Add it to backend/.env or pass api_key explicitly."
            )
        # max_retries=0: same reasoning as OpenAICompatibleProvider — the
        # Anthropic SDK's own retry-on-timeout would otherwise compound with
        # AIOrchestrationService's retry loop and turn one stuck call into a
        # multi-minute silent hang.
        self._client = anthropic.AsyncAnthropic(
            api_key=key, timeout=timeout, max_retries=0
        )
        self._instructor = instructor.from_anthropic(self._client)
        self._model = model
        self._timeout = timeout

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> BaseModel:
        messages = [{"role": "user", "content": prompt}]
        try:
            # max_retries=1: see OpenAICompatibleProvider.generate_structured
            # for why — instructor's own internal retry loop (default 3
            # attempts) must not stack under AIOrchestrationService's retry.
            result = await self._instructor.messages.create(
                model=model or self._model,
                max_tokens=max_tokens,
                system=system or "You are a helpful assistant.",
                messages=messages,
                response_model=schema,
                max_retries=1,
            )
            return result
        except anthropic.APIError as e:
            logger.exception("Anthropic API error")
            message = attach_reset_marker(f"Anthropic API error: {e}", extract_reset_at(e))
            raise LLMProviderError(message) from e
        except Exception as e:
            logger.exception("Unexpected error during structured generation")
            raise LLMProviderError(f"Generation failed: {e}") from e

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        stream: bool = True,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        anthropic_messages = [{"role": m.role, "content": m.content} for m in messages]

        if not stream:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system or "You are a helpful assistant.",
                messages=anthropic_messages,
            )
            yield response.content[0].text
            return

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system or "You are a helpful assistant.",
            messages=anthropic_messages,
        ) as stream_ctx:
            async for text in stream_ctx.text_stream:
                yield text

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ToolChatResult:
        # Translate OpenAI-shaped {"type":"function","function":{name,
        # description,parameters}} tools into Anthropic's flat
        # {name, description, input_schema} shape.
        anthropic_tools = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

        anthropic_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content,
                            }
                        ],
                    }
                )
            elif m.role == "assistant" and m.tool_calls:
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                content.extend(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    for tc in m.tool_calls
                )
                anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system or "You are a helpful assistant.",
                messages=anthropic_messages,
                tools=anthropic_tools,
            )
        except anthropic.APIError as e:
            logger.exception("Anthropic API error during tool-calling chat")
            message = attach_reset_marker(f"Anthropic API error: {e}", extract_reset_at(e))
            raise LLMProviderError(message) from e
        except Exception as e:
            logger.exception("Unexpected error during tool-calling chat")
            raise LLMProviderError(f"Tool-calling chat failed: {e}") from e

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(id=block.id, name=block.name, arguments=block.input)
                )
        return ToolChatResult(content="".join(text_parts) or None, tool_calls=tool_calls)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider="anthropic",
            model=self._model,
            context_window=200_000,
            supports_tools=True,
        )
