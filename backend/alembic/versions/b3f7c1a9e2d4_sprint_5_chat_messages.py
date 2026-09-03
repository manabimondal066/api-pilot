"""sprint_5_chat_messages

Adds `chat_messages`: one row per turn of the AI assistant conversation
(PRD §17, Implementation Plan Module 9). workspace_id is required (FK ->
workspaces, CASCADE); suite_id is optional (FK -> suites, CASCADE) since a
chat message is normally scoped to the suite the assistant panel was opened
from, but the model allows a future workspace-level conversation with no
suite context.

Revision ID: b3f7c1a9e2d4
Revises: 9a1c2e7b5d3f
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3f7c1a9e2d4'
down_revision: Union[str, Sequence[str], None] = '9a1c2e7b5d3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('suite_id', sa.Uuid(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_calls', postgresql.JSONB(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['suite_id'], ['suites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_messages_workspace_id', 'chat_messages', ['workspace_id'])
    op.create_index('ix_chat_messages_suite_id', 'chat_messages', ['suite_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_messages_suite_id', table_name='chat_messages')
    op.drop_index('ix_chat_messages_workspace_id', table_name='chat_messages')
    op.drop_table('chat_messages')
