"""add job freshness/still-open tracking

Adds Job.last_seen_at (stamped every time an ATS sync's live API response
still includes this job -- on first insert AND on every dedup re-scrape)
and Job.is_open (flipped to False by a full sync of that company when a
previously-seen job's external_id no longer appears in the API response).

Before this, a job that got filled/pulled from a company's real board
just stayed in the catalog forever, matchable, with a now-dead apply_url
-- there was no signal anywhere that distinguished "still open" from
"scraped once, months ago, who knows now."

Existing rows backfill is_open=True (their current default) and
last_seen_at=created_at (best available proxy for "last confirmed seen" --
not accurate for anything scraped before this migration, but avoids
leaving every existing row's last_seen_at NULL, which would make them
look artificially fresher than data-less rows should).

Revision ID: b3f8a2c15e9d
Revises: a1c9e6f2d4b7
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f8a2c15e9d'
down_revision: Union[str, None] = 'a1c9e6f2d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('is_open', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE jobs SET last_seen_at = created_at WHERE last_seen_at IS NULL")
    op.create_index('ix_jobs_is_open', 'jobs', ['is_open'])


def downgrade() -> None:
    op.drop_index('ix_jobs_is_open', table_name='jobs')
    op.drop_column('jobs', 'is_open')
    op.drop_column('jobs', 'last_seen_at')
