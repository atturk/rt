"""Chat dello Studio (study_chat_messages)."""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "study_chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("unit_id", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("saved_note_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saved_note_id"], ["study_notes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_study_chat_messages_lesson_id", "study_chat_messages", ["lesson_id"], unique=False)


def downgrade():
    op.drop_index("ix_study_chat_messages_lesson_id", table_name="study_chat_messages")
    op.drop_table("study_chat_messages")
