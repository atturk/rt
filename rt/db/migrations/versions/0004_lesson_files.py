"""lesson storage in the database: lessons.storage, lesson_files

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('lessons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('storage', sa.String(length=16), server_default='folder', nullable=False))

    op.create_table('lesson_files',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lesson_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=1024), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=True),
    sa.Column('media_path', sa.String(length=1024), nullable=True),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('mtime', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lesson_id', 'name', name='uq_lesson_files_lesson_name')
    )
    with op.batch_alter_table('lesson_files', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lesson_files_lesson_id'), ['lesson_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('lesson_files', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lesson_files_lesson_id'))
    op.drop_table('lesson_files')
    with op.batch_alter_table('lessons', schema=None) as batch_op:
        batch_op.drop_column('storage')
