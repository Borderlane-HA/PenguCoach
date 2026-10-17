"""Persist evidence-backed plan execution reviews."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0015_training_reviews'
down_revision = '0014_plan_evolution'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('training_reviews',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.String(80), nullable=False),
        sa.Column('activity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('activities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('data', postgresql.JSONB(), nullable=False),
        sa.Column('ai_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('plan_run_id', 'session_id'))
    for name in ('user_id', 'plan_run_id', 'activity_id'):
        op.create_index('ix_training_reviews_'+name, 'training_reviews', [name])


def downgrade():
    op.drop_table('training_reviews')
