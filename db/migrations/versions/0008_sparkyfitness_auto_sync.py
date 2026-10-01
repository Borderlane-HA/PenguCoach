"""Add incremental automatic SparkyFitness sync settings.

Revision ID: 0008_sparkyfitness_auto_sync
Revises: 0007_garmin_exercise_mappings
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_sparkyfitness_auto_sync"
down_revision = "0007_garmin_exercise_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sparkyfitness_connections" not in set(inspector.get_table_names()):
        raise RuntimeError("PenguCoach baseline schema is missing table 'sparkyfitness_connections'")
    columns = {c["name"] for c in inspector.get_columns("sparkyfitness_connections")}
    if "auto_sync_enabled" not in columns:
        op.add_column("sparkyfitness_connections", sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "sync_interval_minutes" not in columns:
        op.add_column("sparkyfitness_connections", sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="30"))
    if "next_sync_at" not in columns:
        op.add_column("sparkyfitness_connections", sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sparkyfitness_connections" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("sparkyfitness_connections")}
    for name in ("next_sync_at", "sync_interval_minutes", "auto_sync_enabled"):
        if name in columns:
            op.drop_column("sparkyfitness_connections", name)
