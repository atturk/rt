"""state documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('state_documents',
    sa.Column('key', sa.String(length=1024), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('state_documents')
