from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pengucoach.common.config import settings

# Celery executes async tasks via asyncio.run() in worker processes. Reusing
# asyncpg connections from a global QueuePool across short-lived event loops can
# trigger "Event loop is closed" / "attached to a different loop" errors.
# NullPool gives each async session a fresh connection and avoids cross-loop
# connection reuse in both API and worker processes.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    poolclass=NullPool,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
