"""
ChatMessage model — one turn of the AI assistant conversation (PRD §17,
Implementation Plan Module 9).

role values: 'user' | 'assistant'

tool_calls is JSONB, nullable — populated on assistant messages that
invoked tools, storing the list of {name, arguments, result} so the
frontend can show exactly what the agent did (not just the reply text).
Null on user messages and on assistant messages that answered without
calling any tool.

suite_id is nullable: a chat message may be scoped to a suite (the normal
case — the assistant panel is opened from a suite) or, in the future,
workspace-level with no suite context. workspace_id is always set so
history can be queried/purged per tenant even without a suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.suite import Suite
    from app.models.workspace import Workspace


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    __table_args__ = (
        sa.Index("ix_chat_messages_workspace_id", "workspace_id"),
        sa.Index("ix_chat_messages_suite_id", "suite_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    suite_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("suites.id", ondelete="CASCADE"),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(sa.String, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    workspace: Mapped["Workspace"] = relationship(lazy="select")
    suite: Mapped["Suite | None"] = relationship(lazy="select")

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} role={self.role!r} suite_id={self.suite_id}>"
