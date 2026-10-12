"""Note dello Studio (Verifica e Chiedi).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'study_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lesson_id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('anchor', sa.JSON(), nullable=False),
        sa.Column('unit_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('request', sa.Text(), nullable=False),
        sa.Column('response', sa.JSON(), nullable=False),
        sa.Column('model', sa.String(length=256), nullable=True),
        sa.Column('cost', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('applied_decision_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['applied_decision_id'], ['review_decisions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_study_notes_lesson_unit', 'study_notes', ['lesson_id', 'unit_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_study_notes_lesson_unit', table_name='study_notes')
    op.drop_table('study_notes')
