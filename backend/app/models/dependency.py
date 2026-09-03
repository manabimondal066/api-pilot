"""
Dependency model — a directed edge saying one Test must run after another
(PRD §12, Implementation Plan Module 5 / Sprint 4).

source values: 'auto' | 'ai' | 'user'
  'auto' — produced by the heuristic detector (app/services/dependency_detector.py)
  'ai'   — reserved for a future AI-based detection pass (Stage 2, not V1)
  'user' — manually added/overridden by a user

A Dependency row means depends_on_test_id must execute before test_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.test import Test


class Dependency(Base):
    __tablename__ = "dependencies"

    __table_args__ = (
        sa.Index("ix_dependencies_test_id", "test_id"),
        sa.Index("ix_dependencies_depends_on_test_id", "depends_on_test_id"),
        sa.UniqueConstraint(
            "test_id", "depends_on_test_id", name="uq_dependencies_edge"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    test_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("tests.id", ondelete="CASCADE"),
        nullable=False,
    )
    depends_on_test_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("tests.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        server_default=sa.text("'auto'"),
    )
    reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    test: Mapped["Test"] = relationship(
        foreign_keys=[test_id],
        lazy="select",
    )
    depends_on_test: Mapped["Test"] = relationship(
        foreign_keys=[depends_on_test_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Dependency id={self.id} test_id={self.test_id} "
            f"depends_on_test_id={self.depends_on_test_id} source={self.source!r}>"
        )
