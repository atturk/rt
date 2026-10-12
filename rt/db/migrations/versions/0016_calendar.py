"""Tabelle del calendario (settimana tipo, modifiche, stati, note, collegamenti lezioni).

Revision ID: 0016
Revises: 0014
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'calendar_template_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('valid_from', sa.String(length=10), nullable=False),
        sa.Column('valid_to', sa.String(length=10), nullable=True),
        sa.Column('day_of_week', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.String(length=8), nullable=False),
        sa.Column('end_time', sa.String(length=8), nullable=False),
        sa.Column('materia', sa.String(length=256), nullable=False),
        sa.Column('docente', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_calendar_template_valid_day',
        'calendar_template_entries',
        ['valid_from', 'day_of_week'],
        unique=False,
    )

    op.create_table(
        'calendar_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('template_entry_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('start_time', sa.String(length=8), nullable=True),
        sa.Column('end_time', sa.String(length=8), nullable=True),
        sa.Column('materia', sa.String(length=256), nullable=True),
        sa.Column('docente', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['template_entry_id'],
            ['calendar_template_entries.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_calendar_overrides_date', 'calendar_overrides', ['date'], unique=False)

    op.create_table(
        'calendar_day_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_calendar_day_states_date', 'calendar_day_states', ['date'], unique=True)

    op.create_table(
        'calendar_entry_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(length=10), nullable=False),
        sa.Column('entry_key', sa.String(length=128), nullable=False),
        sa.Column('template_entry_id', sa.Integer(), nullable=True),
        sa.Column('override_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('lesson_id', sa.Integer(), nullable=True),
        sa.Column('manual_link', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['template_entry_id'],
            ['calendar_template_entries.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['override_id'],
            ['calendar_overrides.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['lesson_id'],
            ['lessons.id'],
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_calendar_entry_states_date_key',
        'calendar_entry_states',
        ['date', 'entry_key'],
        unique=True,
    )
    op.create_index(
        'ix_calendar_entry_states_lesson_id',
        'calendar_entry_states',
        ['lesson_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_calendar_entry_states_lesson_id', table_name='calendar_entry_states')
    op.drop_index('ix_calendar_entry_states_date_key', table_name='calendar_entry_states')
    op.drop_table('calendar_entry_states')

    op.drop_index('ix_calendar_day_states_date', table_name='calendar_day_states')
    op.drop_table('calendar_day_states')

    op.drop_index('ix_calendar_overrides_date', table_name='calendar_overrides')
    op.drop_table('calendar_overrides')

    op.drop_index('ix_calendar_template_valid_day', table_name='calendar_template_entries')
    op.drop_table('calendar_template_entries')
