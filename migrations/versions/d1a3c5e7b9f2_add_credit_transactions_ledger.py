"""add credit_transactions ledger (charge credits at processing completion)

Revision ID: d1a3c5e7b9f2
Revises: c7e2a9d4f1b8
Create Date: 2026-09-16 10:00:00.000000

Credits move from being DERIVED (counting leads at status sent/draft_created)
to being RECORDED as immutable events. The charge point moves earlier — to the
moment a lead's processing completes (tailored resume + outreach draft both
exist) — which is where the real per-lead LLM cost has been incurred, and
which happens before the Gmail send/draft step.

A ledger is required rather than a status-derived count because
"pending_review" is transient: leads advance to in_review/approved/sent, so a
derived count would decrease over time and give credits back. The unique
(user_id, idempotency_key) constraint makes each charge single-shot across
both processing paths, retries, and re-runs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1a3c5e7b9f2'
down_revision: Union[str, None] = 'c7e2a9d4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'credit_transactions',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('lead_id', sa.UUID(as_uuid=False), nullable=True),
        sa.Column('amount', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('reason', sa.String(), nullable=False, server_default='lead_processed'),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_credit_tx_user_key'),
    )
    op.create_index(op.f('ix_credit_transactions_user_id'), 'credit_transactions', ['user_id'], unique=False)
    op.create_index('ix_credit_transactions_user_created', 'credit_transactions', ['user_id', 'created_at'], unique=False)

    # Backfill: every lead that historically completed processing (has BOTH a
    # tailored resume and an outreach draft) is charged 1 credit, so existing
    # accounts carry their real consumption forward instead of resetting to 0.
    # created_at uses the lead's own updated_at so the ledger reads
    # chronologically. ON CONFLICT DO NOTHING keeps this re-runnable.
    op.execute(
        """
        INSERT INTO credit_transactions
            (id, user_id, lead_id, amount, reason, idempotency_key, created_at)
        SELECT
            gen_random_uuid(),
            l.user_id,
            l.id,
            1,
            'lead_processed',
            'lead_processed:' || l.id::text,
            COALESCE(l.updated_at, l.created_at, NOW())
        FROM leads l
        WHERE COALESCE(NULLIF(TRIM(l.resume_version), ''), NULL) IS NOT NULL
          AND COALESCE(NULLIF(TRIM(l.outreach_draft), ''), NULL) IS NOT NULL
        ON CONFLICT (user_id, idempotency_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index('ix_credit_transactions_user_created', table_name='credit_transactions')
    op.drop_index(op.f('ix_credit_transactions_user_id'), table_name='credit_transactions')
    op.drop_table('credit_transactions')
