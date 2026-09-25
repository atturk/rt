"""schema iniziale

Revision ID: 0001
Revises: 
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('lessons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=1024), nullable=False),
    sa.Column('folder_name', sa.String(length=512), nullable=False),
    sa.Column('data', sa.String(length=32), nullable=False),
    sa.Column('materia', sa.String(length=256), nullable=False),
    sa.Column('titolo', sa.Text(), nullable=False),
    sa.Column('argomenti', sa.Text(), nullable=False),
    sa.Column('workflow_state', sa.String(length=64), nullable=False),
    sa.Column('ledger_sha', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=256), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('issues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lesson_id', sa.Integer(), nullable=False),
    sa.Column('issue_id', sa.String(length=256), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=True),
    sa.Column('severity', sa.String(length=32), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lesson_id', 'issue_id', name='uq_issues_lesson_issue')
    )
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_issues_lesson_id'), ['lesson_id'], unique=False)

    op.create_table('llm_calls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lesson_id', sa.Integer(), nullable=True),
    sa.Column('execution_id', sa.String(length=128), nullable=True),
    sa.Column('request_id', sa.String(length=128), nullable=True),
    sa.Column('job', sa.String(length=64), nullable=True),
    sa.Column('unit_id', sa.String(length=128), nullable=True),
    sa.Column('route_role', sa.String(length=64), nullable=True),
    sa.Column('provider', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=256), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('reasoning_tokens', sa.Integer(), nullable=True),
    sa.Column('total_tokens', sa.Integer(), nullable=True),
    sa.Column('estimated_cost', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=64), nullable=True),
    sa.Column('failure_class', sa.String(length=64), nullable=True),
    sa.Column('timestamp', sa.String(length=64), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('llm_calls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_calls_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_llm_calls_lesson_id'), ['lesson_id'], unique=False)

    op.create_table('phase_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lesson_id', sa.Integer(), nullable=False),
    sa.Column('phase', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('source_fingerprint', sa.String(length=128), nullable=True),
    sa.Column('processor_version', sa.String(length=64), nullable=True),
    sa.Column('stale_reason', sa.Text(), nullable=True),
    sa.Column('started_at', sa.String(length=64), nullable=True),
    sa.Column('finished_at', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lesson_id', 'phase', name='uq_phase_runs_lesson_phase')
    )
    with op.batch_alter_table('phase_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_phase_runs_lesson_id'), ['lesson_id'], unique=False)

    op.create_table('review_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lesson_id', sa.Integer(), nullable=False),
    sa.Column('issue_id', sa.String(length=256), nullable=False),
    sa.Column('decision', sa.String(length=32), nullable=False),
    sa.Column('resolved_text', sa.Text(), nullable=True),
    sa.Column('resolved_by', sa.String(length=64), nullable=False),
    sa.Column('timestamp', sa.String(length=64), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('original_context', sa.Text(), nullable=True),
    sa.Column('channel', sa.String(length=32), nullable=True),
    sa.Column('actor', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('reverted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('review_decisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_review_decisions_issue_id'), ['issue_id'], unique=False)
        batch_op.create_index('ix_review_decisions_lesson_active', ['lesson_id', 'reverted_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('review_decisions', schema=None) as batch_op:
        batch_op.drop_index('ix_review_decisions_lesson_active')
        batch_op.drop_index(batch_op.f('ix_review_decisions_issue_id'))

    op.drop_table('review_decisions')
    with op.batch_alter_table('phase_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_phase_runs_lesson_id'))

    op.drop_table('phase_runs')
    with op.batch_alter_table('llm_calls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_calls_lesson_id'))
        batch_op.drop_index(batch_op.f('ix_llm_calls_execution_id'))

    op.drop_table('llm_calls')
    with op.batch_alter_table('issues', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_issues_lesson_id'))

    op.drop_table('issues')
    op.drop_table('settings')
    op.drop_table('lessons')
