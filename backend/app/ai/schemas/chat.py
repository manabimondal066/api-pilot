from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """One tool call the agent made during a turn, with its result.

    Persisted on the assistant ChatMessage row's tool_calls column, and
    returned to the frontend as part of ChatTurnResult.changes so it can
    show plainly what happened, not just prose (Implementation Plan Module 9).
    """

    tool: str
    arguments: dict
    result: str  # short human-readable outcome, e.g. "Added STATUS_CODE validation to 'Create user'"
    error: str | None = None


class ChatTurnResult(BaseModel):
    reply: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)

    @property
    def changes(self) -> list[ToolCallRecord]:
        """The subset of tool_calls that mutated state (add/remove validation)."""
        from app.ai.tools.chat_tools import MUTATING_TOOLS

        return [tc for tc in self.tool_calls if tc.tool in MUTATING_TOOLS and tc.error is None]
