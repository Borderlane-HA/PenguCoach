from celery import Celery

from pengucoach.common.config import settings

app = Celery("pengucoach", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    timezone="UTC", enable_utc=True,
    task_routes={
        "worker.tasks.garmin_sync.*": {"queue": "garmin"},
        "worker.tasks.fit.*": {"queue": "fit"},
        "worker.tasks.scheduler.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "schedule-due-garmin-syncs": {"task": "worker.tasks.scheduler.schedule_due_garmin_syncs", "schedule": 60.0},
    },
)
app.autodiscover_tasks(["worker.tasks"])
