"""Fine validità delle ore della settimana tipo.

Separata dalla 0016: un database che aveva già creato le tabelle del calendario
prima della colonna la riceve qui. Chi ha installato la 4.2.5b1, dove la colonna
era già nella 0016, la salta.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017'
down_revision: Union[str, None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_valid_to() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns('calendar_template_entries')
    return any(column['name'] == 'valid_to' for column in columns)


def upgrade() -> None:
    if not _has_valid_to():
        with op.batch_alter_table('calendar_template_entries') as batch:
            batch.add_column(sa.Column('valid_to', sa.String(length=10), nullable=True))


def downgrade() -> None:
    if _has_valid_to():
        with op.batch_alter_table('calendar_template_entries') as batch:
            batch.drop_column('valid_to')
