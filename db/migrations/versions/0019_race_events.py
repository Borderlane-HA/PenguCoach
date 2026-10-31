"""Race events (alpha.85): competitions with countdown, prognosis and taper proposal."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0019_race_events'
down_revision = '0018_daily_floors'
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates the current metadata on an empty database, so the table may exist.
    if 'race_events' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'race_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('sport', sa.String(32), nullable=False, server_default='running'),
        sa.Column('distance_km', sa.Float(), nullable=True),
        sa.Column('target_seconds', sa.Integer(), nullable=True),
        sa.Column('priority', sa.String(1), nullable=False, server_default='A'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_race_events_user_id', 'race_events', ['user_id'])
    op.create_index('ix_race_events_date', 'race_events', ['date'])


def downgrade():
    op.drop_index('ix_race_events_date', table_name='race_events')
    op.drop_index('ix_race_events_user_id', table_name='race_events')
    op.drop_table('race_events')
