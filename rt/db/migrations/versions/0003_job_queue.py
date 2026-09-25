"""job queue: jobs, job_events, workers (fase D)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('lesson_path', sa.String(length=1024), nullable=True),
    sa.Column('active_lesson', sa.String(length=1024), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('progress', sa.JSON(), nullable=True),
    sa.Column('decision', sa.JSON(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('worker_id', sa.String(length=128), nullable=True),
    sa.Column('lease_until', sa.DateTime(), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('active_lesson')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jobs_lesson_path'), ['lesson_path'], unique=False)
        batch_op.create_index('ix_jobs_state_created', ['state', 'created_at'], unique=False)

    op.create_table('workers',
    sa.Column('id', sa.String(length=128), nullable=False),
    sa.Column('hostname', sa.String(length=256), nullable=False),
    sa.Column('pid', sa.Integer(), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('job_types', sa.JSON(), nullable=False),
    sa.Column('current_job_id', sa.String(length=36), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen', sa.DateTime(), nullable=False),
    sa.Column('stopped_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('job_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_events_job_id'), ['job_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('job_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_events_job_id'))

    op.drop_table('job_events')
    op.drop_table('workers')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_jobs_state_created')
        batch_op.drop_index(batch_op.f('ix_jobs_lesson_path'))

    op.drop_table('jobs')
