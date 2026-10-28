"""Persist user-specific Garmin strength exercise mappings.

Revision ID: 0007_garmin_exercise_mappings
Revises: 0006_body_profile_metrics
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_garmin_exercise_mappings"
down_revision = "0006_body_profile_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "garmin_exercise_mappings" in set(inspector.get_table_names()):
        return
    op.create_table(
        "garmin_exercise_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=160), nullable=False),
        sa.Column("source_name_normalized", sa.String(length=160), nullable=False),
        sa.Column("garmin_display_name", sa.String(length=180), nullable=False),
        sa.Column("garmin_category", sa.String(length=64), nullable=False),
        sa.Column("garmin_exercise", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_name_normalized"),
    )
    op.create_index("ix_garmin_exercise_mappings_user_id", "garmin_exercise_mappings", ["user_id"], unique=False)
    op.create_index("ix_garmin_exercise_mappings_source_name_normalized", "garmin_exercise_mappings", ["source_name_normalized"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "garmin_exercise_mappings" not in set(inspector.get_table_names()):
        return
    op.drop_index("ix_garmin_exercise_mappings_source_name_normalized", table_name="garmin_exercise_mappings")
    op.drop_index("ix_garmin_exercise_mappings_user_id", table_name="garmin_exercise_mappings")
    op.drop_table("garmin_exercise_mappings")
