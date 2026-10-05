"""study highlights (evidenziazioni dello Studio)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'study_highlights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lesson_id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.String(length=64), nullable=False),
        sa.Column('color', sa.Integer(), nullable=False),
        sa.Column('source', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_study_highlights_lesson_unit', 'study_highlights', ['lesson_id', 'unit_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_study_highlights_lesson_unit', table_name='study_highlights')
    op.drop_table('study_highlights')
