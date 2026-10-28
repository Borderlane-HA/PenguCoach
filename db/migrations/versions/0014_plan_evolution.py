"""Explicit, one-to-one activity assignments for plan evolution.

Revision ID: 0014_plan_evolution
Revises: 0013_activity_performance
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_plan_evolution"
down_revision = "0013_activity_performance"
branch_labels = None
depends_on = None


def upgrade():
    if "plan_activity_matches" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "plan_activity_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(80), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_run_id", "session_id"),
        sa.UniqueConstraint("activity_id"),
    )
    op.create_index("ix_plan_activity_matches_user_id", "plan_activity_matches", ["user_id"])
    op.create_index("ix_plan_activity_matches_plan_run_id", "plan_activity_matches", ["plan_run_id"])


def downgrade():
    op.drop_table("plan_activity_matches")
