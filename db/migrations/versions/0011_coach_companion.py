"""Coach history, explicit memory, daily check-ins and persisted plan calendars."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_coach_companion"
down_revision = "0010_retire_withings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=False, server_default=""))
    op.add_column("messages", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"))
    # Explicit table definitions preserve historical migrations as models evolve.
    for name, key, target in [("coach_profiles", "user_id", "users.id"), ("activity_feedback", "activity_id", "activities.id"), ("plan_schedules", "plan_run_id", "ai_runs.id")]:
        columns = [sa.Column(key, postgresql.UUID(as_uuid=True), sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True)]
        if key != "user_id":
            columns.append(sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True))
        if name == "plan_schedules":
            columns.extend([sa.Column("start_date", sa.Date(), nullable=False), sa.Column("overrides", postgresql.JSONB(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False)])
        else:
            columns.append(sa.Column("data", postgresql.JSONB(), nullable=False))
        columns.append(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        op.create_table(name, *columns)
    for name in ("coach_memories", "coach_checkins"):
        columns = [sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)]
        if name == "coach_memories":
            columns.extend([sa.Column("content", sa.String(1000), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())])
        else:
            columns.extend([sa.Column("date", sa.Date(), nullable=False), sa.Column("data", postgresql.JSONB(), nullable=False), sa.UniqueConstraint("user_id", "date")])
        columns.append(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        op.create_table(name, *columns)


def downgrade():
    for name in ("coach_checkins", "coach_memories", "plan_schedules", "activity_feedback", "coach_profiles"):
        op.drop_table(name)
    op.drop_column("messages", "metadata")
    op.drop_column("conversations", "summary")
