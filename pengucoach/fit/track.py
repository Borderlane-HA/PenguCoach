"""Shared clean-up for GPS tracks without device-computed distance (GPX, TCX, SparkyFitness).

FIT files carry the watch's own distance and speed. GPX tracks and some
SparkyFitness phone recordings only carry raw positions. Summing point-to-point
distances of raw 1 Hz GPS fixes over-counts: position noise adds a zig-zag that
is not part of the route (about +5-10 % on a run), and per-point speed derived
from two fixes shows spikes far above the real pace. This module smooths the
positions within each track segment, drops implausible jumps, derives speed over
a short time window and measures moving time without pauses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

EARTH_RADIUS_M = 6_371_000.0
SMOOTH_POINTS = 5            # centred moving average over GPS fixes
SPEED_WINDOW_S = 5.0         # speed is measured over at least this many seconds
MAX_PLAUSIBLE_SPEED = 45.0   # m/s; faster steps are GPS jumps (tunnel, cold start)
PAUSE_GAP_S = 30.0           # a longer gap between fixes is a pause / auto-pause
MOVING_SPEED = 0.5           # m/s; slower intervals count as standing


def parse_time(value: Any) -> datetime | None:
    """ISO-8601 instant as aware UTC datetime. Mixed fractional seconds and offsets are fine."""
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _haversine(lat1, lon1, lat2, lon2):
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((phi2 - phi1) / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return float(_haversine(lat1, lon1, lat2, lon2))


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce")


def _seconds(df: pd.DataFrame) -> pd.Series:
    if "timestamp" not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return (ts - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()


def _segments(df: pd.DataFrame) -> pd.Series:
    if "track_segment" in df.columns:
        return pd.to_numeric(df["track_segment"], errors="coerce").fillna(0)
    return pd.Series(0, index=df.index)


def add_distance_speed(df: pd.DataFrame) -> pd.DataFrame:
    """Fill cumulative ``distance`` and missing ``speed`` from positions.

    A device distance column with values is kept as-is. Distance does not grow
    across segment breaks: the gap between two GPX segments is not ridden.
    """
    if df.empty:
        return df
    out = df.copy()
    lat, lon = _column(out, "position_lat"), _column(out, "position_long")
    valid_pos = lat.between(-90, 90) & lon.between(-180, 180) & ~((lat == 0) & (lon == 0))
    out.loc[~valid_pos & (lat.notna() | lon.notna()), ["position_lat", "position_long"]] = np.nan
    seconds = _seconds(out)
    segments = _segments(out)
    device_distance = _column(out, "distance")
    has_device_distance = device_distance.notna().sum() >= 2

    step = pd.Series(0.0, index=out.index)
    for _, index in out.groupby(segments, sort=False).groups.items():
        part = valid_pos.loc[index]
        rows = part[part].index
        if len(rows) < 2:
            continue
        # Smooth only dense recordings: averaging sparse fixes (one every 10 s)
        # would cut corners instead of removing noise.
        gaps = seconds.loc[rows].diff().dropna()
        interval = float(gaps.median()) if len(gaps) else float("nan")
        window = SMOOTH_POINTS if interval == interval and interval <= 2 else 3 if interval == interval and interval <= 5 else 1
        smooth_lat = lat.loc[rows].rolling(window, center=True, min_periods=1).mean()
        smooth_lon = lon.loc[rows].rolling(window, center=True, min_periods=1).mean()
        d = pd.Series(_haversine(smooth_lat.shift(), smooth_lon.shift(), smooth_lat, smooth_lon), index=rows).fillna(0.0)
        dt = seconds.loc[rows].diff()
        # A jump faster than any human-powered sport is a GPS glitch, not distance.
        d = d.where(~((dt > 0) & (d / dt > MAX_PLAUSIBLE_SPEED)), 0.0)
        step.loc[rows] = d.values

    if has_device_distance:
        distance = device_distance.ffill().fillna(0.0)
    else:
        distance = step.cumsum()
        out["distance"] = distance

    speed = _column(out, "speed")
    if speed.notna().sum() < max(2, len(out) // 2) and seconds.notna().sum() >= 2:
        derived = pd.Series(np.nan, index=out.index, dtype=float)
        half = SPEED_WINDOW_S / 2
        for _, index in out.groupby(segments, sort=False).groups.items():
            t = seconds.loc[index].to_numpy(dtype=float)
            dist = distance.loc[index].to_numpy(dtype=float)
            ok = ~np.isnan(t)
            if ok.sum() < 2 or np.any(np.diff(t[ok]) < 0):
                continue  # unordered time axis: no invented speed
            tt, dd = t[ok], dist[ok]
            # Centred window: distance covered between t-2.5 s and t+2.5 s,
            # widened to the neighbouring fixes for sparse recordings.
            left = np.minimum(np.searchsorted(tt, tt - half, side="left"), np.arange(len(tt)) - 1).clip(0)
            right = np.maximum(np.searchsorted(tt, tt + half, side="right") - 1, np.arange(len(tt)) + 1).clip(max=len(tt) - 1)
            span = tt[right] - tt[left]
            with np.errstate(divide="ignore", invalid="ignore"):
                values = np.where((span > 0) & (span <= PAUSE_GAP_S * 2), (dd[right] - dd[left]) / span, np.nan)
            values = np.where((values >= 0) & (values <= MAX_PLAUSIBLE_SPEED), values, np.nan)
            full = np.full(len(t), np.nan)
            full[ok] = values
            derived.loc[index] = full
        out["speed"] = speed.where(speed.notna(), derived)
    return out


def moving_seconds(df: pd.DataFrame) -> int | None:
    """Time in motion: gaps (pauses) and standing still do not count."""
    if df.empty or "timestamp" not in df.columns:
        return None
    seconds = _seconds(df)
    if seconds.notna().sum() < 2:
        return None
    segments = _segments(df)
    distance = _column(df, "distance")
    speed = _column(df, "speed")
    total = 0.0
    for _, index in df.groupby(segments, sort=False).groups.items():
        t = seconds.loc[index]
        mask = t.notna()
        t = t[mask]
        dt = t.diff()
        dd = distance.loc[t.index].diff()
        sp = speed.loc[t.index]
        moving_by_distance = (dd / dt) >= MOVING_SPEED
        moving_by_speed = sp >= MOVING_SPEED
        has_motion_data = dd.notna() | sp.notna()
        moving = (dt > 0) & (dt <= PAUSE_GAP_S) & (moving_by_distance | moving_by_speed | ~has_motion_data)
        total += float(dt[moving].sum())
    return int(round(total)) if total > 0 else None
