"""recall sessions per subject (all lessons of a materia)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('recall_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subject', sa.String(length=128), nullable=True))
        batch_op.create_index(batch_op.f('ix_recall_sessions_subject'), ['subject'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('recall_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recall_sessions_subject'))
        batch_op.drop_column('subject')
