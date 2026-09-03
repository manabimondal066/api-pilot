import asyncio
from typing import Any, AsyncIterator

from pydantic import BaseModel

from app.ai.providers.base import Message, ModelInfo, ToolChatResult


class MockProvider:
    """Mock LLM provider for tests. Returns pre-seeded fixtures or default instances.

    Usage:
        provider = MockProvider()
        provider.seed_structured(MyModel, MyModel(...))
        result = await provider.generate_structured("prompt", MyModel)

    For chat_with_tools, seed a queue of turns with seed_tool_turns() — each
    call to chat_with_tools pops the next queued entry, so a multi-turn
    agent loop (tool call -> tool result -> final answer) can be scripted
    precisely. An entry may be a ToolChatResult, or an Exception instance
    (e.g. LLMProviderError) to simulate a provider failure partway through
    a turn — chat_with_tools raises it instead of returning.
    """

    def __init__(self):
        self._structured_responses: dict[type[BaseModel], BaseModel] = {}
        self._structured_error: Exception | None = None
        self._chat_response: str = "Mock chat response."
        self._tool_turns: list[ToolChatResult | Exception] = []
        self.calls: list[dict] = []  # records every call for assertions

    def seed_structured(self, schema: type[BaseModel], response: BaseModel) -> None:
        if not isinstance(response, schema):
            raise TypeError(f"response must be an instance of {schema}")
        self._structured_responses[schema] = response
        self._structured_error = None

    def seed_structured_error(self, exc: Exception) -> None:
        """Make every subsequent call to generate_structured raise *exc*
        instead of returning a seeded response, until seed_structured() is
        called again — simulates a provider failure (e.g. LLMProviderError)
        during test generation, including across AIOrchestrationService's
        own retry attempts.
        """
        self._structured_error = exc

    def seed_chat(self, text: str) -> None:
        self._chat_response = text

    def seed_tool_turns(self, turns: list[ToolChatResult | Exception]) -> None:
        """Queue the sequence of chat_with_tools responses to return, in order.

        Pass an Exception instance in place of a ToolChatResult to have that
        turn raise instead of returning — simulates a provider error (e.g.
        LLMProviderError) partway through a multi-turn tool-calling loop.
        """
        self._tool_turns = list(turns)

    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> BaseModel:
        self.calls.append({
            "method": "generate_structured",
            "prompt": prompt,
            "schema": schema.__name__,
            "system": system,
        })
        await asyncio.sleep(0)  # yield to event loop
        if self._structured_error is not None:
            raise self._structured_error
        if schema in self._structured_responses:
            return self._structured_responses[schema]
        # No seeded response — try to construct a default instance.
        # Will fail loudly if schema has required fields, which is the right behavior.
        return schema()

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        stream: bool = True,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        self.calls.append({
            "method": "chat",
            "messages": [m.model_dump() for m in messages],
            "system": system,
        })
        for chunk in self._chat_response.split(" "):
            await asyncio.sleep(0)
            yield chunk + " "

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ToolChatResult:
        self.calls.append({
            "method": "chat_with_tools",
            "messages": [m.model_dump() for m in messages],
            "tools": [t["function"]["name"] for t in tools],
            "system": system,
        })
        await asyncio.sleep(0)
        if not self._tool_turns:
            raise AssertionError(
                "MockProvider.chat_with_tools called with no seeded turns left — "
                "call seed_tool_turns() with enough turns for the whole loop"
            )
        turn = self._tool_turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider="mock",
            model="mock-model",
            context_window=999999,
            supports_tools=True,
        )
