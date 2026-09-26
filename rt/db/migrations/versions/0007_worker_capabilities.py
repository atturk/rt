"""worker capabilities (RT4-G1: stt)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('capabilities', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('workers', schema=None) as batch_op:
        batch_op.drop_column('capabilities')
