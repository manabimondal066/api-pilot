"""sprint_5_suite_environment_id

Adds `suites.environment_id` (nullable FK -> environments.id, ON DELETE
SET NULL): the environment auto-created/matched for a cURL import (see
app/services/import_service.py, app/services/environment_service.py). Null
for Swagger/Postman imports, which still require manual environment setup.

Revision ID: 9a1c2e7b5d3f
Revises: 84c71e05fc7e
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9a1c2e7b5d3f'
down_revision: Union[str, Sequence[str], None] = '84c71e05fc7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('suites', sa.Column('environment_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_suites_environment_id_environments',
        'suites', 'environments',
        ['environment_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_suites_environment_id_environments', 'suites', type_='foreignkey')
    op.drop_column('suites', 'environment_id')
