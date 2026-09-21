from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import activities, admin_ai, admin_users, auth, coach, garmin, health, jobs, setup, settings as user_settings
from pengucoach.common.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Database schema is managed by Alembic during install/update.
    yield


app = FastAPI(title="PenguCoach API", version=settings.app_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for router in (setup.router, auth.router, garmin.router, health.router, activities.router, jobs.router, coach.router, user_settings.router, admin_ai.router, admin_users.router): app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def healthcheck() -> dict[str, str]: return {"status": "ok", "version": settings.app_version}
