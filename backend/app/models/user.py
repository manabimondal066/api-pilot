"""
User model — member of a workspace.

Roles: 'admin' | 'member'
Password stored as bcrypt hash — never plaintext.
Auth logic lives in Sprint 9; this model is schema-only for now.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        # The unique index on email doubles as a lookup index — no separate ix needed.
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(sa.String, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String, nullable=False)
    role: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        server_default=sa.text("'member'"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"
