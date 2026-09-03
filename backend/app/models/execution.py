"""
Execution + ExecutionResult models — deterministic test-run records (PRD
§14, §24). No AI involved: an Execution is created when a single test is
run against an Environment, and its ExecutionResult captures exactly what
was sent, what came back, and which validations passed or failed.

Execution.status values:      'running' | 'completed' | 'error' | 'skipped'
ExecutionResult.status values: 'passed' | 'failed' | 'inconclusive' | 'error' | 'skipped'

'inconclusive' (Fix B — grounded validations, app/services/validation_
enforcement.py): every *enforced* validation passed, but one or more
*advisory* (ungrounded) validations failed — the request behaved correctly
by every check we trust, but at least one unverified guess didn't match.
Deliberately distinct from 'failed', which only 'enforced' validations can
produce; see app/services/execution_engine.py execute() for the exact
aggregation rule.

V1 runs a single test synchronously (see app/services/execution_service.py
docstring) so an Execution always has exactly one ExecutionResult. The two
tables are kept separate (rather than folding result columns onto
Execution) so a future suite-level execution can attach multiple results
to one Execution without a schema change.
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
    from app.models.environment import Environment
    from app.models.test import Test


class Execution(Base):
    __tablename__ = "executions"

    __table_args__ = (
        sa.Index("ix_executions_test_id", "test_id"),
        sa.Index("ix_executions_environment_id", "environment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    test_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("tests.id", ondelete="CASCADE"),
        nullable=False,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        server_default=sa.text("'running'"),
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    test: Mapped["Test"] = relationship(lazy="select")
    environment: Mapped["Environment"] = relationship(lazy="select")
    results: Mapped[list["ExecutionResult"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Execution id={self.id} test_id={self.test_id} status={self.status!r}>"


class ExecutionResult(Base):
    __tablename__ = "execution_results"

    __table_args__ = (
        sa.Index("ix_execution_results_execution_id", "execution_id"),
        sa.Index("ix_execution_results_test_id", "test_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    test_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("tests.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(sa.String, nullable=False)

    request_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    validation_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    execution: Mapped["Execution"] = relationship(
        back_populates="results",
        lazy="select",
    )
    test: Mapped["Test"] = relationship(lazy="select")

    def __repr__(self) -> str:
        return (
            f"<ExecutionResult id={self.id} execution_id={self.execution_id} "
            f"status={self.status!r}>"
        )
