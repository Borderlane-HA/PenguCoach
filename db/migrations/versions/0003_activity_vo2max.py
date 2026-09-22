"""Normalize Garmin activity VO2 max for running/cycling history.

Revision ID: 0003_activity_vo2max
Revises: 0002_ai_runs
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_activity_vo2max"
down_revision = "0002_ai_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "activities" not in inspector.get_table_names():
        raise RuntimeError(
            "PenguCoach baseline schema is missing table 'activities'. "
            "For a fresh installation use install/proxmox/install-app.sh, "
            "which bootstraps the current schema before stamping Alembic."
        )
    columns = {column["name"] for column in inspector.get_columns("activities")}
    if "vo2max" not in columns:
        op.add_column("activities", sa.Column("vo2max", sa.Float(), nullable=True))

    # Existing Garmin activity summaries already retain the complete raw payload.
    # Backfill only when Garmin stored a numeric VO2 value; missing remains NULL.
    op.execute(
        """
        UPDATE activities
        SET vo2max = CASE
            WHEN jsonb_typeof(raw -> 'vO2MaxValue') = 'number'
                THEN (raw ->> 'vO2MaxValue')::double precision
            WHEN jsonb_typeof(raw -> 'vo2MaxValue') = 'number'
                THEN (raw ->> 'vo2MaxValue')::double precision
            ELSE NULL
        END
        WHERE vo2max IS NULL
          AND raw IS NOT NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "activities" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("activities")}
    if "vo2max" in columns:
        op.drop_column("activities", "vo2max")
