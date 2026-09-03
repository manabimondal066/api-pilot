import json
import logging
import os
from typing import Any, AsyncIterator

import instructor
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.ai.providers.base import (
    LLMProvider,
    LLMProviderError,
    Message,
    ModelInfo,
    ToolCallRequest,
    ToolChatResult,
)
from app.ai.providers.errors import attach_reset_marker, extract_reset_at

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """Works with any OpenAI-compatible endpoint.

    Verified targets:
      - NVIDIA NIM: base_url="https://integrate.api.nvidia.com/v1"
        Models: "meta/llama-3.3-70b-instruct", "meta/llama-3.1-70b-instruct"
      - Groq: base_url="https://api.groq.com/openai/v1"
        Models: "llama-3.3-70b-versatile"
      - OpenAI: base_url="https://api.openai.com/v1" (default)
        Models: "gpt-4o-mini", "gpt-4o"
      - Local Ollama: base_url="http://localhost:11434/v1"
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: str = "openai_compatible",
        context_window: int = 128_000,
        timeout: float = 120.0,
        instructor_mode: instructor.Mode = instructor.Mode.JSON,
    ):
        if not api_key:
            raise LLMProviderError("API key is required for OpenAICompatibleProvider")
        # max_retries=0: the OpenAI SDK retries failed/timed-out requests on
        # its own by default (2 retries, each re-running the full `timeout`
        # plus backoff sleep). That compounds silently with the retry loop
        # in AIOrchestrationService.generate_tests, turning one slow/stuck
        # call into a multi-minute hang with no visible error. One retry
        # layer is enough — leave it to the orchestration service, which
        # also knows about schema-validation failures, not just transport
        # ones.
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0
        )
        self._instructor = instructor.from_openai(self._client, mode=instructor_mode)
        self._model = model
        self._provider_name = provider_name
        self._context_window = context_window
        self._base_url = base_url

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> BaseModel:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            # max_retries=1: instructor retries internally by default (3
            # attempts) on top of whatever the OpenAI client itself does.
            # That's a second, independent retry layer stacked underneath
            # AIOrchestrationService's own retry loop — three nested retry
            # loops turned one slow/rate-limited call into a multi-minute
            # hang with no visible progress. One attempt here; retries are
            # the orchestration service's job.
            result = await self._instructor.chat.completions.create(
                model=model or self._model,
                max_tokens=max_tokens,
                messages=messages,
                response_model=schema,
                max_retries=1,
            )
            return result
        except openai.APIError as e:
            logger.exception("OpenAI-compatible API error from %s", self._base_url)
            message = attach_reset_marker(
                f"LLM API error ({self._provider_name}): {e}", extract_reset_at(e)
            )
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
        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        openai_messages.extend({"role": m.role, "content": m.content} for m in messages)

        if not stream:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=openai_messages,
            )
            yield response.choices[0].message.content or ""
            return

        stream_resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=openai_messages,
            stream=True,
        )
        async for chunk in stream_resp:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ToolChatResult:
        openai_messages: list[dict[str, Any]] = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "tool":
                openai_messages.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
                )
            elif m.role == "assistant" and m.tool_calls:
                openai_messages.append({
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                            **(tc.extra or {}),
                        }
                        for tc in m.tool_calls
                    ],
                })
            else:
                openai_messages.append({"role": m.role, "content": m.content})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=openai_messages,
                tools=tools,
                tool_choice="auto",
            )
        except openai.APIError as e:
            logger.exception("OpenAI-compatible API error from %s", self._base_url)
            message = attach_reset_marker(
                f"LLM API error ({self._provider_name}): {e}", extract_reset_at(e)
            )
            raise LLMProviderError(message) from e
        except Exception as e:
            logger.exception("Unexpected error during tool-calling chat")
            raise LLMProviderError(f"Tool-calling chat failed: {e}") from e

        message = response.choices[0].message
        tool_calls = []
        for tc in message.tool_calls or []:
            # Anything the SDK attached beyond the standard id/type/function
            # shape is a vendor extra (e.g. Gemini's extra_content) that must
            # be replayed verbatim on the next request — see chat_with_tools'
            # message-building above. Not Gemini-specific: whatever shows up
            # here is captured, so this also covers other providers' future
            # extras without a per-vendor branch.
            extra = {
                k: v for k, v in tc.model_dump().items() if k not in ("id", "type", "function")
            } or None
            tool_calls.append(
                ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments or "{}"),
                    extra=extra,
                )
            )
        return ToolChatResult(content=message.content, tool_calls=tool_calls)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider=self._provider_name,
            model=self._model,
            context_window=self._context_window,
            supports_tools=True,
        )
