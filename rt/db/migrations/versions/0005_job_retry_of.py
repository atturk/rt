"""jobs.retry_of: il job nuovo creato da 'Riprova' punta a quello fallito

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retry_of', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_jobs_retry_of'), ['retry_of'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_retry_of'))
        batch_op.drop_column('retry_of')
