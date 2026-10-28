"""Garmin connection method: password login or official Personal API key."""
from alembic import op
import sqlalchemy as sa

revision = '0016_garmin_personal_api'
down_revision = '0015_training_reviews'
branch_labels = None
depends_on = None

COLUMNS = (
    ('auth_mode', lambda: sa.Column('auth_mode', sa.String(32), nullable=False, server_default='password')),
    ('api_key_ciphertext', lambda: sa.Column('api_key_ciphertext', sa.Text(), nullable=True)),
    ('api_key_hint', lambda: sa.Column('api_key_hint', sa.String(16), nullable=True)),
    ('api_key_expires_on', lambda: sa.Column('api_key_expires_on', sa.Date(), nullable=True)),
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
