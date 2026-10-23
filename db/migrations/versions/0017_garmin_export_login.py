"""Optional Garmin login for workout export next to a Personal API key."""
from alembic import op
import sqlalchemy as sa

revision = '0017_garmin_export_login'
down_revision = '0016_garmin_personal_api'
branch_labels = None
depends_on = None

COLUMNS = (
    ('export_token_ciphertext', lambda: sa.Column('export_token_ciphertext', sa.Text(), nullable=True)),
    ('export_display_name', lambda: sa.Column('export_display_name', sa.String(255), nullable=True)),
    ('export_status', lambda: sa.Column('export_status', sa.String(32), nullable=True)),
    ('export_error_code', lambda: sa.Column('export_error_code', sa.String(128), nullable=True)),
)


def upgrade():
    # 0001 creates the current metadata on an empty database, so columns may exist.
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('garmin_connections')}
    for name, column in COLUMNS:
        if name not in existing:
            op.add_column('garmin_connections', column())


def downgrade():
    for name, _ in reversed(COLUMNS):
        op.drop_column('garmin_connections', name)
