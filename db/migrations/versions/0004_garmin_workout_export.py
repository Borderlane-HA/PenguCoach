"""Add explicit Garmin workout-calendar export opt-in and export ledger.

Revision ID: 0004_garmin_workout_export
Revises: 0003_activity_vo2max
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_garmin_workout_export"
down_revision = "0003_activity_vo2max"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "garmin_sync_settings" not in tables or "ai_runs" not in tables:
        raise RuntimeError("PenguCoach baseline schema is incomplete; expected garmin_sync_settings and ai_runs")

    sync_columns = {column["name"] for column in inspector.get_columns("garmin_sync_settings")}
    if "workout_export_enabled" not in sync_columns:
        op.add_column(
            "garmin_sync_settings",
            sa.Column("workout_export_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if "garmin_workout_exports" not in tables:
        op.create_table(
            "garmin_workout_exports",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("plan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", sa.String(length=80), nullable=False),
            sa.Column("scheduled_date", sa.Date(), nullable=False),
            sa.Column("workout_id", sa.String(length=128), nullable=True),
            sa.Column("scheduled_workout_id", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("error_message_safe", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["plan_run_id"], ["ai_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "plan_run_id", "session_id", "scheduled_date"),
        )
        op.create_index("ix_garmin_workout_exports_user_id", "garmin_workout_exports", ["user_id"], unique=False)
        op.create_index("ix_garmin_workout_exports_plan_run_id", "garmin_workout_exports", ["plan_run_id"], unique=False)
        op.create_index("ix_garmin_workout_exports_session_id", "garmin_workout_exports", ["session_id"], unique=False)
        op.create_index("ix_garmin_workout_exports_scheduled_date", "garmin_workout_exports", ["scheduled_date"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "garmin_workout_exports" in tables:
        op.drop_table("garmin_workout_exports")
    if "garmin_sync_settings" in tables:
        columns = {column["name"] for column in inspector.get_columns("garmin_sync_settings")}
        if "workout_export_enabled" in columns:
            op.drop_column("garmin_sync_settings", "workout_export_enabled")
