"""Token di input letti dalla cache del prompt, nullable per le chiamate storiche."""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("cached_input_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "cached_input_tokens")
