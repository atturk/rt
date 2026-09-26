"""recall sessions registry and app -> Telegram bot commands

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
    op.create_table('recall_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lesson_path', sa.String(length=1024), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('qtype', sa.String(length=16), nullable=True),
    sa.Column('chat_id', sa.String(length=64), nullable=True),
    sa.Column('thread_id', sa.String(length=64), nullable=True),
    sa.Column('question_ids', sa.JSON(), nullable=False),
    sa.Column('summary', sa.JSON(), nullable=True),
    sa.Column('started_at', sa.String(length=64), nullable=False),
    sa.Column('ended_at', sa.String(length=64), nullable=True),
    sa.Column('ended_by', sa.String(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('recall_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recall_sessions_lesson_path'), ['lesson_path'], unique=False)
        batch_op.create_index('ix_recall_sessions_state_channel', ['state', 'channel'], unique=False)

    op.create_table('telegram_commands',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('lesson_path', sa.String(length=1024), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('processed_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('telegram_commands', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_commands_lesson_path'), ['lesson_path'], unique=False)
        batch_op.create_index('ix_telegram_commands_state', ['state', 'id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('telegram_commands', schema=None) as batch_op:
        batch_op.drop_index('ix_telegram_commands_state')
        batch_op.drop_index(batch_op.f('ix_telegram_commands_lesson_path'))
    op.drop_table('telegram_commands')
    with op.batch_alter_table('recall_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_recall_sessions_state_channel')
        batch_op.drop_index(batch_op.f('ix_recall_sessions_lesson_path'))
    op.drop_table('recall_sessions')
