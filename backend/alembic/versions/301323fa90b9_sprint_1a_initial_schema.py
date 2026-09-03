"""sprint_1a_initial_schema

Creates the five core tables for Sprint 1 (workspaces, users, specs,
suites, endpoints) and seeds a default workspace and admin user.

Revision ID: 301323fa90b9
Revises:
Create Date: 2026-05-25 23:04:32.320842
"""

import uuid
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "301323fa90b9"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all Sprint 1 tables and seed the default workspace + admin user."""

    # ------------------------------------------------------------------
    # 1. workspaces — top-level tenant container
    # ------------------------------------------------------------------
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # 2. specs — imported API specification metadata
    # ------------------------------------------------------------------
    op.create_table(
        "specs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_specs_workspace_id", "specs", ["workspace_id"], unique=False)

    # ------------------------------------------------------------------
    # 3. users — workspace members
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.String(),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # ------------------------------------------------------------------
    # 4. suites — named collection of endpoints extracted from a spec
    # ------------------------------------------------------------------
    op.create_table(
        "suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("spec_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "generation_status",
            sa.String(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["spec_id"], ["specs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suites_spec_id", "suites", ["spec_id"], unique=False)
    op.create_index("ix_suites_workspace_id", "suites", ["workspace_id"], unique=False)

    # ------------------------------------------------------------------
    # 5. endpoints — individual parsed API operations
    # ------------------------------------------------------------------
    op.create_table(
        "endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["suite_id"], ["suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_endpoints_suite_id", "endpoints", ["suite_id"], unique=False)

    # ------------------------------------------------------------------
    # Seed: default workspace + admin user
    #
    # The fixed workspace UUID is exported as DEFAULT_WORKSPACE_ID in
    # app/core/constants.py and used throughout Sprint 1–8 as the
    # stand-in for per-user workspace resolution (lands in Sprint 9).
    #
    # bcrypt hash is computed at migration runtime — never hardcoded.
    #
    # sa.bindparam(..., type_=sa.Uuid()) is required: asyncpg infers
    # VARCHAR for untyped text() params; explicit types produce $1::UUID.
    # ------------------------------------------------------------------
    _workspace_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    _admin_id = uuid.uuid4()
    _password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")

    op.execute(
        sa.text(
            "INSERT INTO workspaces (id, name, created_at, updated_at) "
            "VALUES (:id, :name, now(), now())"
        ).bindparams(
            sa.bindparam("id", value=_workspace_id, type_=sa.Uuid()),
            sa.bindparam("name", value="Default Workspace"),
        )
    )

    op.execute(
        sa.text(
            "INSERT INTO users "
            "  (id, email, password_hash, role, workspace_id, created_at) "
            "VALUES "
            "  (:id, :email, :password_hash, :role, :workspace_id, now())"
        ).bindparams(
            sa.bindparam("id", value=_admin_id, type_=sa.Uuid()),
            sa.bindparam("email", value="admin@local"),
            sa.bindparam("password_hash", value=_password_hash),
            sa.bindparam("role", value="admin"),
            sa.bindparam("workspace_id", value=_workspace_id, type_=sa.Uuid()),
        )
    )


def downgrade() -> None:
    """Drop all Sprint 1 tables (seed data removed with the tables)."""
    op.drop_index("ix_endpoints_suite_id", table_name="endpoints")
    op.drop_table("endpoints")
    op.drop_index("ix_suites_workspace_id", table_name="suites")
    op.drop_index("ix_suites_spec_id", table_name="suites")
    op.drop_table("suites")
    op.drop_table("users")
    op.drop_index("ix_specs_workspace_id", table_name="specs")
    op.drop_table("specs")
    op.drop_table("workspaces")
