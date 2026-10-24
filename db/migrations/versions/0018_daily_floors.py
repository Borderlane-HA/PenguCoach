"""Floors climbed per day (Garmin daily summary, SparkyFitness daily metrics)."""
from alembic import op
import sqlalchemy as sa

revision = '0018_daily_floors'
down_revision = '0017_garmin_export_login'
branch_labels = None
depends_on = None

COLUMNS = (
    ('floors_ascended', lambda: sa.Column('floors_ascended', sa.Float(), nullable=True)),
    ('floors_descended', lambda: sa.Column('floors_descended', sa.Float(), nullable=True)),
)


def upgrade():
    # 0001 creates the current metadata on an empty database, so columns may exist.
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('daily_health')}
    for name, column in COLUMNS:
        if name not in existing:
            op.add_column('daily_health', column())


def downgrade():
    for name, _ in reversed(COLUMNS):
        op.drop_column('daily_health', name)
