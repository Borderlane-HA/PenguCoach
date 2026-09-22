"""Add height and bone mass to body measurements.

Revision ID: 0006_body_profile_metrics
Revises: 0005_sparkyfitness_connection
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_body_profile_metrics"
down_revision = "0005_sparkyfitness_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "body_measurements" not in set(inspector.get_table_names()):
        raise RuntimeError("PenguCoach baseline schema is missing table 'body_measurements'")
    columns = {col["name"] for col in inspector.get_columns("body_measurements")}
    if "height_cm" not in columns:
        op.add_column("body_measurements", sa.Column("height_cm", sa.Float(), nullable=True))
    if "bone_mass_kg" not in columns:
        op.add_column("body_measurements", sa.Column("bone_mass_kg", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "body_measurements" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("body_measurements")}
    if "bone_mass_kg" in columns:
        op.drop_column("body_measurements", "bone_mass_kg")
    if "height_cm" in columns:
        op.drop_column("body_measurements", "height_cm")
