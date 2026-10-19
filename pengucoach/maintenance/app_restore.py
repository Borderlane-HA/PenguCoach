"""Run only inside the application's own Python environment, with writers stopped."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, update

from pengucoach.db.models import AiRun, BackgroundJob, GarminSyncRun
from pengucoach.db.session import SessionLocal

RESTORED_JOB = 'RESTORE_INTERRUPTED_JOB'


async def normalize_restored_jobs(db):
    now = datetime.now(timezone.utc)
    await db.execute(update(BackgroundJob).where(BackgroundJob.status.not_in(['finished','failed','cancelled']))
                     .values(status='cancelled',finished_at=now,message=RESTORED_JOB))
    await db.execute(update(GarminSyncRun).where(GarminSyncRun.status=='running')
                     .values(status='cancelled',finished_at=now,error_code=RESTORED_JOB))
    # Keep completed/partial answers and continuation checkpoints; release only dead queue claims.
    rows = await db.stream(select(AiRun.id,AiRun.metadata_json).execution_options(yield_per=50))
    try:
        async for identifier,meta in rows:
            if isinstance(meta,dict) and '_continuation_job' in meta:
                meta={key:value for key,value in meta.items() if key!='_continuation_job'}
                await db.execute(update(AiRun).where(AiRun.id==identifier).values(metadata_json=meta))
    finally:await rows.close()
    await db.commit()


async def main():
    async with SessionLocal() as db:await normalize_restored_jobs(db)


if __name__=='__main__':asyncio.run(main())
