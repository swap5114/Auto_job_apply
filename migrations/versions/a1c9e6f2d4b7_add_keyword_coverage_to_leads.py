"""add keyword_coverage to leads

Phase 5.5: persists skills/tailor_resume.py's keyword_coverage() score
(a rough ATS-keyword-overlap %, not a real ATS simulation) on the Lead
row itself, so it survives past the graph run that computed it and can
be surfaced to a human reviewer (e.g. the Apply channel's review UI)
without recomputing it. Purely informational -- "sane," not "enforced,"
per PHASE_5_PLAN.md 5.5's own wording; nothing blocks on this value.

Revision ID: a1c9e6f2d4b7
Revises: f515db178b1b
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e6f2d4b7'
down_revision: Union[str, None] = 'f515db178b1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('keyword_coverage', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('leads', 'keyword_coverage')
