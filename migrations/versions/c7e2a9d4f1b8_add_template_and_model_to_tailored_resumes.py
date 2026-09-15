"""add template + model_used to tailored_resumes

Revision ID: c7e2a9d4f1b8
Revises: b5d1f3a7c9e2
Create Date: 2026-09-15 13:30:00.000000

Records which visual template (standard | jake) a tailored resume was
rendered with, and which model produced it (vertex/gemini vs vertex_claude
after ATS-floor escalation).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7e2a9d4f1b8'
down_revision: Union[str, None] = 'b5d1f3a7c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tailored_resumes', sa.Column('template', sa.String(), nullable=False, server_default='jake'))
    op.add_column('tailored_resumes', sa.Column('model_used', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('tailored_resumes', 'model_used')
    op.drop_column('tailored_resumes', 'template')
