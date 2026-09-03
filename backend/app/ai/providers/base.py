from typing import Any, Protocol, AsyncIterator
from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """One tool invocation the model asked for."""
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Vendor-specific fields the SDK attached to this tool call beyond the
    # standard id/type/function shape (e.g. Gemini's
    # extra_content.google.thought_signature) that must be replayed verbatim
    # on the next request or the provider rejects the follow-up turn. None
    # when the SDK attached nothing extra — every other provider is
    # unaffected.
    extra: dict[str, Any] | None = None


class Message(BaseModel):
    """One chat message."""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # Set only on role="tool" messages — the id of the ToolCallRequest this
    # message answers (see ToolChatResult.tool_calls). Providers that need a
    # different wire shape (e.g. Anthropic's tool_result content blocks)
    # translate from this flat representation internally.
    tool_call_id: str | None = None
    # Set only on role="assistant" messages that requested tool calls (i.e.
    # replaying a prior ToolChatResult.tool_calls back into history) — both
    # OpenAI and Anthropic need the *original* tool-call request replayed
    # verbatim on the assistant turn a tool-result message is answering.
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)


class ModelInfo(BaseModel):
    """Static info about the provider's model."""
    provider: str       # "anthropic" | "mock"
    model: str          # e.g. "claude-sonnet-4-5"
    context_window: int
    supports_tools: bool


class ToolChatResult(BaseModel):
    """Result of one chat_with_tools turn.

    Either `content` is set (the model produced a final text answer) or
    `tool_calls` is non-empty (the model wants tools run before it
    continues) — callers should treat a non-empty tool_calls list as taking
    priority, since some providers return both a partial content string and
    tool calls on the same turn.
    """
    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)


class LLMProvider(Protocol):
    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> BaseModel:
        """Generate a response that conforms to the given Pydantic schema."""
        ...

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        stream: bool = True,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream a chat response. Yields text chunks."""
        ...

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ToolChatResult:
        """One non-streaming turn of tool-calling chat.

        `tools` uses OpenAI's function-calling schema shape
        (`[{"type": "function", "function": {"name", "description",
        "parameters"}}]`) regardless of provider — implementations translate
        to their own wire format internally. Multi-turn tool loops are the
        caller's responsibility (append a role="tool" Message per
        ToolCallRequest.id and call again).
        """
        ...

    def get_model_info(self) -> ModelInfo: ...


class LLMProviderError(Exception):
    """Raised when the provider fails (network, auth, malformed output, etc)."""
