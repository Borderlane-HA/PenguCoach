"""Retire connector credentials; keep imported observations and historical migration chain."""
from alembic import op
import sqlalchemy as sa
revision = "0010_retire_withings"
down_revision = "0009_withings_connection"
branch_labels = None
depends_on = None

def upgrade():
    if "withings_connections" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("withings_connections")

def downgrade():
    # Credentials cannot be restored; the earlier revision can recreate an empty table.
    import importlib
    importlib.import_module("db.migrations.versions.0009_withings_connection").upgrade()
