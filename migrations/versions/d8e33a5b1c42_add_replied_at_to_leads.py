"""add replied_at to leads

Revision ID: d8e33a5b1c42
Revises: c7d21e4f9a30
Create Date: 2026-08-27 11:00:00.000000

Timestamp of when a contact's reply was first detected (v1 Task 7), so the
dashboard's reply funnel reflects real replies.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8e33a5b1c42'
down_revision: Union[str, None] = 'c7d21e4f9a30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('leads', 'replied_at')
