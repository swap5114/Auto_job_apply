"""add user_settings table (per-user pipeline config + search criteria)

Revision ID: a2b4c6d8e0f2
Revises: 197ee0b15fff
Create Date: 2026-09-14 10:00:00.000000

C-1 fix: replaces the shared global config/.env pipeline knobs and
config/search_criteria.json with a per-user row, so one tenant's settings
edits can never overwrite another tenant's.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a2b4c6d8e0f2'
down_revision: Union[str, None] = '197ee0b15fff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_settings',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('pipeline_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('search_criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_user_settings_user'),
    )
    op.create_index(op.f('ix_user_settings_user_id'), 'user_settings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_settings_user_id'), table_name='user_settings')
    op.drop_table('user_settings')
