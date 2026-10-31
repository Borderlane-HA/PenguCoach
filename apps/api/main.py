from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routers import activities, companion, admin_ai, admin_users, auth, coach, garmin, garmin_workouts, health, jobs, setup, sparkyfitness, settings as user_settings, weather
from pengucoach.common import maintenance_mode
from pengucoach.common.config import settings
from apps.api.routers import maps, plan_evolution, insights, session_features, training_workspace


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Database schema is managed by Alembic during install/update.
    yield


app = FastAPI(title="PenguCoach API", version=settings.resolved_app_version, lifespan=lifespan)
# Sign-in/out, cancelling running jobs (helps the drain) and the maintenance area
# itself stay usable while maintenance waits for background work.
MAINTENANCE_ALLOWED = ("/api/v1/auth/", "/api/v1/admin/system")


def _maintenance_allowed(path: str) -> bool:
    return path.startswith(MAINTENANCE_ALLOWED) or (path.startswith("/api/v1/jobs/") and path.endswith("/cancel"))


@app.middleware("http")
async def maintenance_guard(request: Request, call_next):
    if (request.method not in {"GET", "HEAD", "OPTIONS"} and not _maintenance_allowed(request.url.path)
            and await maintenance_mode.active_async()):
        return JSONResponse({"detail": "MAINTENANCE_ACTIVE"}, status_code=503, headers={"Retry-After": "30"})
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for router in (setup.router, auth.router, garmin.router, garmin_workouts.router, sparkyfitness.router, health.router, activities.router, jobs.router, coach.router, companion.router, user_settings.router, weather.router, admin_ai.router, admin_users.router): app.include_router(router, prefix="/api/v1")
app.include_router(plan_evolution.router, prefix="/api/v1")
app.include_router(maps.router, prefix="/api/v1")
app.include_router(insights.router, prefix="/api/v1")


@app.get("/health")
async def healthcheck() -> dict[str, str]: return {"status": "ok", "version": settings.resolved_app_version}

app.include_router(session_features.router, prefix="/api/v1")
app.include_router(training_workspace.router, prefix="/api/v1")

from apps.api.routers import execution, continuation
app.include_router(execution.router, prefix="/api/v1")
app.include_router(continuation.router, prefix="/api/v1")

from apps.api.routers import admin_system
app.include_router(admin_system.router, prefix="/api/v1")

from apps.api.routers import calendar, races
app.include_router(calendar.router, prefix="/api/v1")
app.include_router(races.router, prefix="/api/v1")
