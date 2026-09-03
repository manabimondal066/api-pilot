"""sprint_4_dependencies_table

Adds `dependencies` (PRD §12, Implementation Plan Module 5, Sprint 4): a
directed edge saying one Test must run after another. Populated by the
Stage 1 heuristic detector (app/services/dependency_detector.py) in V1,
with room for 'ai'/'user' sourced edges later.

Revision ID: 84c71e05fc7e
Revises: 64fd55f9c4b4
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '84c71e05fc7e'
down_revision: Union[str, Sequence[str], None] = '64fd55f9c4b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('dependencies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('test_id', sa.Uuid(), nullable=False),
    sa.Column('depends_on_test_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(), server_default=sa.text("'auto'"), nullable=False),
    sa.Column('reason', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['test_id'], ['tests.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['depends_on_test_id'], ['tests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('test_id', 'depends_on_test_id', name='uq_dependencies_edge')
    )
    op.create_index('ix_dependencies_test_id', 'dependencies', ['test_id'], unique=False)
    op.create_index('ix_dependencies_depends_on_test_id', 'dependencies', ['depends_on_test_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_dependencies_depends_on_test_id', table_name='dependencies')
    op.drop_index('ix_dependencies_test_id', table_name='dependencies')
    op.drop_table('dependencies')
