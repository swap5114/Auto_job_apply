"""add tailored_resumes table (per-lead/company tailored resume JSON + artifact keys)

Revision ID: b5d1f3a7c9e2
Revises: a2b4c6d8e0f2
Create Date: 2026-09-15 12:00:00.000000

Tailored resume JSON (small, queryable) lives in Postgres; the rendered
PDF/Markdown artifacts live in object storage (storage/artifact_store.py) with
only their keys stored here. Replaces the flat, ephemeral resumes/ disk files
that didn't survive multi-instance/Cloud Run deploys, and powers the Resume
page's tailored-history list.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b5d1f3a7c9e2'
down_revision: Union[str, None] = 'a2b4c6d8e0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tailored_resumes',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('lead_id', sa.UUID(as_uuid=False), nullable=True),
        sa.Column('company', sa.String(), nullable=True),
        sa.Column('role', sa.String(), nullable=True),
        sa.Column('tailored_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('keyword_coverage', sa.Float(), nullable=True),
        sa.Column('pdf_key', sa.String(), nullable=True),
        sa.Column('md_key', sa.String(), nullable=True),
        sa.Column('legacy_version', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='pipeline'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tailored_resumes_user_id'), 'tailored_resumes', ['user_id'], unique=False)
    op.create_index(op.f('ix_tailored_resumes_lead_id'), 'tailored_resumes', ['lead_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tailored_resumes_lead_id'), table_name='tailored_resumes')
    op.drop_index(op.f('ix_tailored_resumes_user_id'), table_name='tailored_resumes')
    op.drop_table('tailored_resumes')
