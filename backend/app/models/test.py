"""
Test model — a single AI-generated (or user-authored) test case against an
endpoint. Mirrors the TestCase Pydantic schema in
``app/ai/schemas/test_case.py`` (see Implementation Plan §7.2), persisted so
generated tests survive past a single orchestration call.

category values: 'POSITIVE' | 'NEGATIVE' | 'EDGE'
method values:   'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
created_by values: 'ai' | 'user'

validations / extractions / depends_on are stored as JSONB — they mirror the
Validation / Extraction Pydantic models and a list of dependency test IDs
respectively; see app/ai/schemas/test_case.py for the exact shape.

version increments each time a test is edited (manually or by the AI via
regeneration) — no history table in V1; last-write-wins.
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
    from app.models.endpoint import Endpoint
    from app.models.suite import Suite


class Test(Base):
    __tablename__ = "tests"

    __table_args__ = (
        sa.Index("ix_tests_suite_id", "suite_id"),
        sa.Index("ix_tests_endpoint_id", "endpoint_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("suites.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    category: Mapped[str] = mapped_column(sa.String, nullable=False)
    method: Mapped[str] = mapped_column(sa.String, nullable=False)
    path: Mapped[str] = mapped_column(sa.String, nullable=False)

    headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    query_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    body: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    validations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    extractions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    depends_on: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )

    confidence: Mapped[float] = mapped_column(
        sa.Float, nullable=False, server_default=sa.text("0.5")
    )
    ai_notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        sa.String, nullable=False, server_default=sa.text("'ai'")
    )
    version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    suite: Mapped["Suite"] = relationship(
        back_populates="tests",
        lazy="select",
    )
    endpoint: Mapped["Endpoint"] = relationship(
        back_populates="tests",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Test id={self.id} name={self.name!r} "
            f"category={self.category!r} confidence={self.confidence}>"
        )
