"""Tour planner (alpha.87): saved tours and installation-wide app settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0020_tour_planner'
down_revision = '0019_race_events'
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates the current metadata on an empty database, so the tables may exist.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'planned_tours' not in existing:
        op.create_table(
            'planned_tours',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('sport', sa.String(32), nullable=False),
            sa.Column('mode', sa.String(16), nullable=False, server_default='round'),
            sa.Column('distance_m', sa.Float(), nullable=False, server_default='0'),
            sa.Column('ascent_m', sa.Float(), nullable=False, server_default='0'),
            sa.Column('duration_s', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('geometry', postgresql.JSONB(), nullable=False, server_default='[]'),
            sa.Column('summary', postgresql.JSONB(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_planned_tours_user_id', 'planned_tours', ['user_id'])
    if 'app_settings' not in existing:
        op.create_table(
            'app_settings',
            sa.Column('key', sa.String(64), primary_key=True),
            sa.Column('value', postgresql.JSONB(), nullable=False, server_default='{}'),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade():
    op.drop_table('app_settings')
    op.drop_index('ix_planned_tours_user_id', table_name='planned_tours')
    op.drop_table('planned_tours')
