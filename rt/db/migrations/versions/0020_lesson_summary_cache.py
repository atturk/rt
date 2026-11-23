"""Vetrina persistente riepiloghi lezioni (lesson_summary_cache)."""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lesson_summary_cache",
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("schema", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("lesson_summary_cache")
