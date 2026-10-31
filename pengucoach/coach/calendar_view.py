"""Calendar page (alpha.85): year heatmap, streaks and the iCalendar feed.

Streaks are kind on purpose: rest days never break a week streak, and the
current week or today only counts once it is reached – an unfinished day or
week does not reset anything.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def active_week_streaks(session_days: Iterable[date], today: date, minimum: int = 2) -> dict[str, int]:
    """Weeks in a row with at least ``minimum`` training days."""
    counts: dict[date, set[date]] = {}
    for day in session_days:
        counts.setdefault(week_start(day), set()).add(day)
    good = {w for w, days in counts.items() if len(days) >= minimum}
    this_week = week_start(today)
    current, cursor = 0, this_week if this_week in good else this_week - timedelta(days=7)
    while cursor in good:
        current += 1
        cursor -= timedelta(days=7)
    best, run, previous = 0, 0, None
    for w in sorted(good):
        run = run + 1 if previous and w - previous == timedelta(days=7) else 1
        best, previous = max(best, run), w
    return {"current": current, "best": best, "this_week_days": len(counts.get(this_week, ())), "minimum": minimum}


def step_goal_streaks(steps_by_day: dict[date, float], target_for, today: date) -> dict[str, int]:
    """Days in a row with the step goal reached. Days without data end a streak."""
    reached = {d for d, v in steps_by_day.items() if v is not None and v >= target_for(d)}
    current, cursor = 0, today if today in reached else today - timedelta(days=1)
    while cursor in reached:
        current += 1
        cursor -= timedelta(days=1)
    best, run, previous = 0, 0, None
    for d in sorted(reached):
        run = run + 1 if previous and d - previous == timedelta(days=1) else 1
        best, previous = max(best, run), d
    return {"current": current, "best": best, "reached_days": len(reached)}


def level(value: float | None, thresholds: tuple[float, float, float]) -> int:
    """0 = nothing, 1–4 = intensity bucket for the heatmap colour."""
    if not value or value <= 0:
        return 0
    a, b, c = thresholds
    return 1 if value < a else 2 if value < b else 3 if value < c else 4


# --- iCalendar --------------------------------------------------------------

def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue with a leading space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_calendar(events: list[dict[str, Any]], *, name: str, host: str = "pengucoach") -> str:
    """Build a VCALENDAR. Events: uid, title, description, date (all-day) or start+minutes, url."""
    now = _stamp(datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PenguCoach//Calendar//DE", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(name)}", "X-PUBLISHED-TTL:PT1H", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    for event in events:
        uid = hashlib.sha1(str(event["uid"]).encode()).hexdigest() + f"@{host}"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}"]
        if event.get("start"):
            start: datetime = event["start"]
            end = start + timedelta(minutes=max(5, int(event.get("minutes") or 30)))
            lines += [f"DTSTART:{_stamp(start)}", f"DTEND:{_stamp(end)}"]
        else:
            day: date = event["date"]
            lines += [f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}"]
        lines.append(f"SUMMARY:{_escape(event['title'])}")
        if event.get("description"):
            lines.append(f"DESCRIPTION:{_escape(event['description'])}")
        if event.get("category"):
            lines.append(f"CATEGORIES:{_escape(event['category'])}")
        if event.get("url"):
            lines.append(f"URL:{event['url']}")
        if event.get("transparent"):
            lines.append("TRANSP:TRANSPARENT")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
