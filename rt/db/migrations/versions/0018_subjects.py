"""Registro materie.

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("subjects"):
        op.create_table("subjects",
            sa.Column("nome", sa.String(256), primary_key=True),
            sa.Column("creata_il", sa.DateTime(), nullable=False))


def downgrade():
    if sa.inspect(op.get_bind()).has_table("subjects"):
        op.drop_table("subjects")
