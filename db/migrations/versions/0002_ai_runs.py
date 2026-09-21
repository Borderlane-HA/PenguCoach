"""Persist AI analyses and generated training plans.

Revision ID: 0002_ai_runs
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_ai_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_name", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_runs_user_id", "ai_runs", ["user_id"])
    op.create_index("ix_ai_runs_task_type", "ai_runs", ["task_type"])
    op.create_index("ix_ai_runs_activity_id", "ai_runs", ["activity_id"])
    op.create_index("ix_ai_runs_created_at", "ai_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_runs")
