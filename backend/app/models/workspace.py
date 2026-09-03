"""
Workspace model — top-level tenant container.

Every user, spec, suite, and endpoint belongs to a workspace.
The default workspace (id 00000000-0000-0000-0000-000000000001) is seeded
in the initial migration and used as a constant until auth lands in Sprint 9.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.spec import Spec
    from app.models.suite import Suite


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
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

    specs: Mapped[list["Spec"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="select",
    )
    suites: Mapped[list["Suite"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} name={self.name!r}>"
