"""Add read-only SparkyFitness connection settings.

Revision ID: 0005_sparkyfitness_connection
Revises: 0004_garmin_workout_export
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_sparkyfitness_connection"
down_revision = "0004_garmin_workout_export"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        raise RuntimeError("PenguCoach baseline schema is incomplete; expected users")
    if "sparkyfitness_connections" in tables:
        return
    op.create_table(
        "sparkyfitness_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="disconnected"),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sync_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("sync_sleep", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_daily_health", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_activities", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_sync_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_sparkyfitness_connections_user_id", "sparkyfitness_connections", ["user_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sparkyfitness_connections" in set(inspector.get_table_names()):
        op.drop_table("sparkyfitness_connections")
