#!/usr/bin/env python3
"""Create the current PenguCoach schema for a genuinely fresh database.

Fresh installations bootstrap directly from the reviewed SQLAlchemy metadata and
then stamp Alembic at the current head. Existing installations continue to use
normal Alembic upgrades. This avoids replaying historical migrations against an
empty database while keeping upgrade history intact for real deployments.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from pengucoach.common.config import settings
from pengucoach.db.base import Base
import pengucoach.db.models  # noqa: F401  # register all tables on Base.metadata


async def main() -> None:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
