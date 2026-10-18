"""Personal step targets. Missing days are never converted to zero steps."""
from datetime import date, timedelta
from math import ceil

from sqlalchemy import select

from pengucoach.common.dates import user_today
from pengucoach.db.models import DailyHealth, UserPreference


def goal_config(pref):
    cfg = (pref.dashboard_config or {}).get("step_goal", {}) if pref else {}
    target = cfg.get("daily_target", 8000)
    target = target if type(target) is int and 1000 <= target <= 50000 else 8000
    history = []
    for item in cfg.get("history", []):
        try:
            day = date.fromisoformat(item["from"])
            value = item["target"]
            if type(value) is int and 1000 <= value <= 50000:
                history.append({"from": day.isoformat(), "target": value})
        except (ValueError, TypeError, KeyError):
            continue
    return {"configured": cfg.get("configured") is True, "daily_target": target,
            "adaptive": cfg.get("adaptive") is True, "history": sorted(history, key=lambda x: x["from"])}


def target_on(config, day):
    history = config["history"]
    matching = [h for h in history if h["from"] <= str(day)]
    return matching[-1]["target"] if matching else history[0]["target"] if history else config["daily_target"]


def summarize_steps(rows, config, *, today, period_days=None):
    # One authoritative merged DailyHealth row per local day; tolerate repeated inputs.
    values = {}
    for row in rows:
        day, steps = row.date, row.steps
        if day <= today and type(steps) in (int, float) and steps >= 0:
            values[day] = steps
    count, total = len(values), round(sum(values.values()))
    goal_total = sum(target_on(config, day) for day in values) if config["configured"] else 0
    first = config["history"][0]["from"] if config["history"] else today.isoformat()
    return {"configured": config["configured"], "daily_target": config["daily_target"],
            "adaptive": config["adaptive"], "recorded_days": count, "period_days": period_days,
            "total_steps": total, "goal_total": goal_total,
            "percent": round(total / goal_total * 100, 1) if goal_total else None,
            "achieved_days": sum(steps >= target_on(config, day) for day, steps in values.items()) if goal_total else 0,
            "reference_days": sum(str(day) < first for day in values) if goal_total else 0}


def goal_suggestion(rows, config, today):
    if not config["configured"] or not config["adaptive"]:
        return None
    history = config["history"]
    if history and date.fromisoformat(history[-1]["from"]) > today - timedelta(days=7):
        return None
    values = {r.date: r.steps for r in rows if today - timedelta(days=14) <= r.date < today
              and type(r.steps) in (int, float) and r.steps >= 0}
    if len(values) < 10:
        return None
    target = config["daily_target"]
    achieved = sum(value >= target_on(config, day) for day, value in values.items()) / len(values)
    average = sum(values.values()) / len(values)
    proposed, reason = target, None
    if achieved >= .85:
        proposed, reason = min(50000, target + min(500, max(250, ceil(target * .05 / 250) * 250))), "consistently_reached"
    elif achieved <= .25 and average < target * .8:
        proposed, reason = max(1000, target - max(250, int(target * .1 / 250) * 250)), "rarely_reached"
    return {"daily_target": proposed, "direction": "up" if proposed > target else "down",
            "reason": reason, "recorded_days": len(values), "average_steps": round(average)} if proposed != target else None


async def step_goal_payload(db, user):
    today = user_today(user)
    config = goal_config(await db.get(UserPreference, user.id))
    rows = (await db.execute(select(DailyHealth.date, DailyHealth.steps).where(
        DailyHealth.user_id == user.id, DailyHealth.date >= today - timedelta(days=14), DailyHealth.date < today
    ))).all() if config["adaptive"] else []
    return {**config, "suggestion": goal_suggestion(rows, config, today), "date": today.isoformat()}
