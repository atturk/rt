"""Tabella llm_deferred per richieste LLM in modalità batch."""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "llm_deferred",
        sa.Column("key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("lesson_path", sa.String(1024), nullable=True),
        sa.Column("batch_id", sa.String(256), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("credential_ref", sa.String(128), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_deferred_job_id", "llm_deferred", ["job_id"])
    op.create_index("ix_llm_deferred_lesson_path", "llm_deferred", ["lesson_path"])
    op.create_index("ix_llm_deferred_batch_id", "llm_deferred", ["batch_id"])
    op.create_index("ix_llm_deferred_state", "llm_deferred", ["state"])
    op.create_index("ix_llm_deferred_job_state", "llm_deferred", ["job_id", "state"])
    op.create_index("ix_llm_deferred_batch_state", "llm_deferred", ["batch_id", "state"])


def downgrade():
    op.drop_index("ix_llm_deferred_batch_state", table_name="llm_deferred")
    op.drop_index("ix_llm_deferred_job_state", table_name="llm_deferred")
    op.drop_index("ix_llm_deferred_state", table_name="llm_deferred")
    op.drop_index("ix_llm_deferred_batch_id", table_name="llm_deferred")
    op.drop_index("ix_llm_deferred_lesson_path", table_name="llm_deferred")
    op.drop_index("ix_llm_deferred_job_id", table_name="llm_deferred")
    op.drop_table("llm_deferred")
