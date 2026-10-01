"""Activity journal performance indexes.

Revision ID: 0013_activity_performance
Revises: 0012_training_intelligence
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_activity_performance"
down_revision = "0012_training_intelligence"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "activities" not in set(sa.inspect(bind).get_table_names()):
        return
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes("activities")}
    if "ix_activities_user_started_at" not in existing:
        op.create_index("ix_activities_user_started_at", "activities", ["user_id", "started_at"])
    if "ix_activities_user_fit_status" not in existing:
        op.create_index("ix_activities_user_fit_status", "activities", ["user_id", "fit_status"])
    if "ix_activities_user_manual_source" not in existing:
        op.create_index(
            "ix_activities_user_manual_source", "activities", ["user_id"],
            postgresql_where=sa.text("(raw ->> 'source') = 'manual_upload'"),
        )
    if "ix_activities_user_sparky_source" not in existing:
        op.create_index(
            "ix_activities_user_sparky_source", "activities", ["user_id"],
            postgresql_where=sa.text("raw ? 'sparkyfitness'"),
        )


def downgrade():
    bind = op.get_bind()
    if "activities" not in set(sa.inspect(bind).get_table_names()):
        return
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes("activities")}
    for name in (
        "ix_activities_user_sparky_source",
        "ix_activities_user_manual_source",
        "ix_activities_user_fit_status",
        "ix_activities_user_started_at",
    ):
        if name in existing:
            op.drop_index(name, table_name="activities")
