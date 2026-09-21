from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pengucoach.db.models import Activity, ActivityMetric, DailyHealth, HrvDaily, SleepSession, User


async def build_coach_context(db: AsyncSession, user: User) -> dict:
    start = date.today() - timedelta(days=30)
    health = (await db.scalars(select(DailyHealth).where(DailyHealth.user_id == user.id, DailyHealth.date >= start).order_by(DailyHealth.date.desc()).limit(31))).all()
    sleep = (await db.scalars(select(SleepSession).where(SleepSession.user_id == user.id, SleepSession.date >= start).order_by(SleepSession.date.desc()).limit(31))).all()
    hrv = (await db.scalars(select(HrvDaily).where(HrvDaily.user_id == user.id, HrvDaily.date >= start).order_by(HrvDaily.date.desc()).limit(31))).all()
    activities = (await db.scalars(select(Activity).where(Activity.user_id == user.id).order_by(Activity.started_at.desc()).limit(12))).all()
    activity_context = []
    for a in activities:
        metric = await db.scalar(select(ActivityMetric).where(ActivityMetric.activity_id == a.id))
        activity_context.append({"id": str(a.id), "date": a.started_at, "name": a.name, "sport": a.sport_type, "distance_m": a.distance_m, "duration_s": a.duration_seconds, "avg_hr": a.avg_hr, "load": a.training_load, "fit_metrics": {"hr_drift": metric.hr_drift, "aerobic_decoupling": metric.aerobic_decoupling, "pace_consistency": metric.pace_consistency} if metric else None})
    return {
        "source_notice": "Garmin values and PenguCoach-calculated metrics. Missing values are null and must not be invented.",
        "health_30d": [{"date": x.date, "steps": x.steps, "rhr": x.resting_hr, "stress": x.stress_avg, "body_battery_high": x.body_battery_high, "hydration_ml": x.hydration_ml, "hydration_goal_ml": x.hydration_goal_ml, "training_readiness": x.training_readiness, "vo2max_running": x.vo2max_running} for x in health],
        "sleep_30d": [{"date": x.date, "duration_s": x.duration_seconds, "score": x.sleep_score, "deep_s": x.deep_seconds, "rem_s": x.rem_seconds} for x in sleep],
        "hrv_30d": [{"date": x.date, "overnight": x.overnight_average, "status": x.garmin_status} for x in hrv],
        "recent_activities": activity_context,
    }
