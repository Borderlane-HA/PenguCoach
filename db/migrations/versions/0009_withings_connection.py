"""Add read-only Withings OAuth connection and automatic sync settings.

Revision ID: 0009_withings_connection
Revises: 0008_sparkyfitness_auto_sync
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_withings_connection"
down_revision = "0008_sparkyfitness_auto_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "withings_connections" in set(inspector.get_table_names()):
        return
    op.create_table(
        "withings_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="disconnected"),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("withings_user_id", sa.String(length=128), nullable=True),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("oauth_state", sa.String(length=255), nullable=True),
        sa.Column("oauth_state_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_body", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_daily_activity", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_sleep", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_cursors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_sync_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_withings_connections_user_id", "withings_connections", ["user_id"], unique=True)
    op.create_index("ix_withings_connections_oauth_state", "withings_connections", ["oauth_state"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "withings_connections" in set(inspector.get_table_names()):
        op.drop_table("withings_connections")
