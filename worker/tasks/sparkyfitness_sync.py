from __future__ import annotations

import asyncio
import uuid

from worker.celery_app import app


def _run(coro):
    return asyncio.run(coro)


@app.task(bind=True, name="worker.tasks.sparkyfitness_sync.sync_user")
def sync_user(self, user_id: str, incremental: bool = False):
    async def work():
        from pengucoach.db.session import SessionLocal
        from pengucoach.sparkyfitness.sync import sync_sparkyfitness

        async with SessionLocal() as db:
            def progress(payload: dict):
                self.update_state(state="PROGRESS", meta=payload)
            return await sync_sparkyfitness(db, uuid.UUID(user_id), progress=progress, incremental=incremental)

    return _run(work())
