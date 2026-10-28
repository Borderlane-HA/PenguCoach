"""Training intelligence decision log.

Revision ID: 0012_training_intelligence
Revises: 0011_coach_companion
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_training_intelligence"
down_revision = "0011_coach_companion"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "coach_decision_logs" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "coach_decision_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("after", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_coach_decision_logs_user_id", "coach_decision_logs", ["user_id"])
    op.create_index("ix_coach_decision_logs_plan_run_id", "coach_decision_logs", ["plan_run_id"])
    op.create_index("ix_coach_decision_logs_session_id", "coach_decision_logs", ["session_id"])
    op.create_index("ix_coach_decision_logs_created_at", "coach_decision_logs", ["created_at"])


def downgrade():
    bind = op.get_bind()
    if "coach_decision_logs" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("coach_decision_logs")
