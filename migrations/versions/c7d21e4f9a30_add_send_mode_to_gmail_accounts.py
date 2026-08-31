"""add send_mode to gmail_accounts

Revision ID: c7d21e4f9a30
Revises: b3f8a2c15e9d
Create Date: 2026-08-27 10:00:00.000000

Per-user Gmail send preference ("draft" | "direct"), replacing the old global
GMAIL_DIRECT_SEND env flag (v1, Task 5).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d21e4f9a30'
down_revision: Union[str, None] = 'b3f8a2c15e9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'gmail_accounts',
        sa.Column('send_mode', sa.String(), nullable=False, server_default='draft'),
    )
    # Drop the server default now that existing rows are backfilled -- the
    # application layer sets the value explicitly on every write.
    op.alter_column('gmail_accounts', 'send_mode', server_default=None)


def downgrade() -> None:
    op.drop_column('gmail_accounts', 'send_mode')
