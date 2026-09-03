"""
Environment model — connection details for a real API to test against
(e.g. "QA", "Staging"): base URL, auth config, default headers, variables.

SECURITY (V1 known gap): auth_config is stored as PLAIN TEXT JSONB. It is
not encrypted at rest. Encrypting this column (e.g. via application-level
envelope encryption or a KMS-backed field) is a required hardening step
before production use with real credentials — see PRD §32.1. Do not treat
this as done; it is deliberately deferred, not silently skipped.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class Environment(Base):
    __tablename__ = "environments"

    __table_args__ = (
        sa.Index("ix_environments_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    base_url: Mapped[str] = mapped_column(sa.String, nullable=False)
    auth_type: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        server_default=sa.text("'none'"),
    )
    # Plain-text credential storage — see module docstring SECURITY note.
    auth_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    default_headers: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    variables: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
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

    workspace: Mapped["Workspace"] = relationship(lazy="select")

    def __repr__(self) -> str:
        return f"<Environment id={self.id} name={self.name!r} base_url={self.base_url!r}>"
