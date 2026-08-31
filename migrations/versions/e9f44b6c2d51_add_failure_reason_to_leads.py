"""add failure_reason to leads

Revision ID: e9f44b6c2d51
Revises: d8e33a5b1c42
Create Date: 2026-08-27 12:00:00.000000

Short machine reason a lead is stuck/needs attention (v1 Task 11), so pipeline
failures are visible and retriable on the dashboard instead of silent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e9f44b6c2d51'
down_revision: Union[str, None] = 'd8e33a5b1c42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('failure_reason', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('leads', 'failure_reason')
