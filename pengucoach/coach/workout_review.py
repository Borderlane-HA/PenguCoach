"""Recorded-sample goal review and GPS-verified route comparisons. No AI calls."""
from __future__ import annotations

import bisect
import math
from statistics import mean


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def flatten_steps(steps, depth=0):
    if depth > 5:
        raise ValueError("PLAN_TOO_COMPLEX")
    result = []
    for step in steps or []:
        if step.get("type") == "repeat":
            result.extend(flatten_steps(step.get("steps"), depth + 1) * min(100, int(step.get("repeat") or 0)))
        else:
            result.append(step)
        if len(result) > 1000:
            raise ValueError("PLAN_TOO_COMPLEX")
    return result


def _interpolate(xs, ys, x, *, recorded_times=None):
    if x > xs[-1] or x < xs[0]:
        return None
    i = bisect.bisect_left(xs, x)
    if i == 0 or xs[i] == x:
        return ys[i]
    if recorded_times is not None and recorded_times[i]-recorded_times[i-1] > 30:
        return None
    span = xs[i] - xs[i-1]
    return ys[i-1] + (ys[i]-ys[i-1]) * (x-xs[i-1]) / span if span > 0 else ys[i]


def _outcome(buckets):
    total = sum(buckets.values())
    if not total:
        return "unassessed"
    if buckets["in"]/total >= .7:
        return "on_target"
    if max(buckets["above"], buckets["below"])/total < .3:
        return "mixed"
    return "too_high" if buckets["above"] > buckets["below"] else "too_low"


def evaluate_goals(series, session, profiles, *, offset_s=0):
    """Start at recording start. Gaps >30s and track breaks are unobserved.

    Weight readings by real seconds; never invent a 1 Hz recording. Distance
    step boundaries use recorded monotonic distance, not average speed.
    """
    steps = flatten_steps(session.get("steps"))
    result = {"status": "unassessed", "steps": [], "planned_seconds": 0, "observed_seconds": 0,
              "in_target_pct": None, "method": "recording_start_time_weighted", "reason": None}
    times = [number(r.get("elapsed_s")) for r in series]
    if len(times) < 2 or any(t is None for t in times) or any(b < a for a, b in zip(times, times[1:])) or times[-1] <= times[0]:
        result["reason"] = "missing_time"
        return result
    times = [t-times[0]-offset_s for t in times]
    distances = [number(r.get("distance_km")) for r in series]
    distance_ok = all(d is not None for d in distances) and all(b >= a for a, b in zip(distances, distances[1:]))
    cursor, totals = 0.0, {"below": 0.0, "in": 0.0, "above": 0.0}
    for index, step in enumerate(steps):
        duration = number(step.get("duration_seconds"))
        end = cursor + duration if duration is not None else None
        reason = None
        if end is None:
            if not distance_ok:
                reason = "missing_distance"
            elif cursor > times[-1]:
                reason = "not_recorded"
            else:
                start_distance = _interpolate(times, distances, cursor, recorded_times=times)
                length = number(step.get("distance_meters"))
                target_distance = start_distance + length/1000 if start_distance is not None and length is not None else None
                end = _interpolate(distances, times, target_distance, recorded_times=times) if target_distance is not None else None
                if end is None:
                    reason = "distance_boundary_gap" if start_distance is None or (target_distance is not None and target_distance <= distances[-1]) else "distance_not_completed"
        target = step.get("target") or {}
        kind, zone = target.get("type", "none"), target.get("zone")
        row = {"index": index+1, "type": step.get("type"), "description": step.get("description", ""),
               "target_type": kind, "zone": zone, "start_s": round(cursor, 1), "end_s": round(end, 1) if end is not None else None,
               "status": "unassessed", "reason": reason, "coverage_pct": 0, "below_pct": None, "in_target_pct": None, "above_pct": None}
        if end is None:
            result["steps"].append(row)
            result["reason"] = reason
            break  # Subsequent interval boundaries cannot be known.
        bounds = next((z for z in profiles.get(kind, []) if z.get("zone") == zone), None)
        low, high = (number(bounds.get("low", bounds.get("low_bpm", bounds.get("low_w")))), number(bounds.get("high", bounds.get("high_bpm", bounds.get("high_w"))))) if bounds else (None, None)
        if kind != "none":
            result["planned_seconds"] += end-cursor
        if kind == "none":
            row.update(status="free", reason="no_target")
        elif bounds is None or (low is None and high is None):
            row["reason"] = "missing_zones"
        else:
            metric = "heart_rate" if kind == "heart_rate_zone" else "power"
            buckets = {"below": 0.0, "in": 0.0, "above": 0.0}
            for i in range(bisect.bisect_right(times, cursor)-1, min(len(series)-1, bisect.bisect_left(times, end)+1)):
                if i < 0:
                    continue
                dt = times[i+1]-times[i]
                row_a, row_b = series[i], series[i+1]
                if dt <= 0 or dt > 30 or row_a.get("track_segment") != row_b.get("track_segment"):
                    continue
                overlap = max(0.0, min(end, times[i+1])-max(cursor, times[i]))
                value = number(row_a.get(metric))
                if value is None or value < 0 or (metric == "heart_rate" and value <= 0):
                    continue
                bucket = "below" if low is not None and value < low else "above" if high is not None and value > high else "in"
                buckets[bucket] += overlap
            observed = sum(buckets.values())
            planned = end-cursor
            row.update(low=low, high=high, observed_seconds=round(observed, 1), coverage_pct=round(100*observed/planned, 1) if planned else 0)
            if observed:
                row.update(below_pct=round(100*buckets["below"]/observed, 1), in_target_pct=round(100*buckets["in"]/observed, 1), above_pct=round(100*buckets["above"]/observed, 1))
            row["status"] = "unassessed" if row["coverage_pct"] < 70 else _outcome(buckets)
            row["reason"] = "sparse_sensor" if row["coverage_pct"] < 70 else None
            result["observed_seconds"] += observed
            for key in totals:
                totals[key] += buckets[key]
        result["steps"].append(row)
        cursor = end
    assessed = [r for r in result["steps"] if r["status"] in {"on_target", "too_high", "too_low", "mixed"}]
    coverage = 100*result["observed_seconds"]/result["planned_seconds"] if result["planned_seconds"] else 0
    result["coverage_pct"] = round(coverage, 1)
    if assessed and coverage >= 70 and not result["reason"]:
        result["in_target_pct"] = round(100*totals["in"]/sum(totals.values()), 1)
        result["status"] = "partial" if any(r["status"] == "unassessed" for r in result["steps"]) else _outcome(totals)
    if not steps:
        result["reason"] = "no_steps"
    elif not result["planned_seconds"] and not result["reason"]:
        result["reason"] = "no_resolved_targets"
    return result


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def gps_points(series):
    points = []
    for index, row in enumerate(series):
        lat, lon = number(row.get("position_lat")), number(row.get("position_long"))
        if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180:
            points.append((lat, lon, index))
    return points


def sampled(points, count=48):
    return [points[round(i*(len(points)-1)/(min(count, len(points))-1))] for i in range(min(count, len(points)))] if len(points) > 1 else points


def route_match(reference, candidate, *, segment=False):
    """Conservative ordered shape match; route length alone cannot match.

    Require endpoints within 100m and 95% of sampled points within 80m in
    both directions, monotonic progress and comparable recorded distance.
    """
    a, b = gps_points(reference), gps_points(candidate)
    if len(a) < 12 or len(b) < 12 or len(a)/max(1, len(reference)) < .8 or len(b)/max(1, len(candidate)) < .8:
        return None
    if len({r.get("track_segment") for r in reference}) > 1 or len({r.get("track_segment") for r in candidate}) > 1:
        return None
    if segment:
        start = min(range(len(b)), key=lambda i: haversine(a[0], b[i]))
        ends = [i for i in range(start+1, len(b)) if haversine(a[-1], b[i]) <= 100]
        if not ends:
            return None
        end = min(ends, key=lambda i: haversine(a[-1], b[i]))
        b = b[start:end+1]
    if haversine(a[0], b[0]) > 100 or haversine(a[-1], b[-1]) > 100:
        return None
    a_dist = number(reference[a[-1][2]].get("distance_km"))
    a_start = number(reference[a[0][2]].get("distance_km"))
    b_dist = number(candidate[b[-1][2]].get("distance_km"))
    b_start = number(candidate[b[0][2]].get("distance_km"))
    if None in (a_dist, a_start, b_dist, b_start) or a_dist-a_start < .2 or abs((b_dist-b_start)/(a_dist-a_start)-1) > .12:
        return None
    gaps = []
    for source, target in ((a, b), (b, a)):
        progress = []
        probes = sampled(source)
        for probe_index, p in enumerate(probes):
            # A closed loop's finish shares its start coordinate. Honour the
            # recording endpoints rather than matching the finish to index 0.
            index = 0 if probe_index == 0 else len(target)-1 if probe_index == len(probes)-1 else min(range(len(target)), key=lambda i: haversine(p, target[i]))
            progress.append(index)
            gaps.append(haversine(p, target[index]))
        if any(y < x-2 for x, y in zip(progress, progress[1:])):
            return None
    if sum(d <= 80 for d in gaps)/len(gaps) < .95:
        return None
    return {"start_index": b[0][2], "end_index": b[-1][2], "mean_gap_m": round(mean(gaps), 1)}


def route_metrics(series):
    if len(series) < 2:
        return {}
    result = {}
    start, end = number(series[0].get("elapsed_s")), number(series[-1].get("elapsed_s"))
    if start is not None and end is not None and end > start:
        result["elapsed_seconds"] = round(end-start, 1)
    ds, de = number(series[0].get("distance_km")), number(series[-1].get("distance_km"))
    if ds is not None and de is not None and de > ds:
        result["distance_km"] = round(de-ds, 3)
    for metric, output in (("heart_rate", "avg_hr"), ("power", "avg_power"), ("speed_kmh", "avg_speed_kmh")):
        pairs = []
        for a, b in zip(series, series[1:]):
            ta, tb, value = number(a.get("elapsed_s")), number(b.get("elapsed_s")), number(a.get(metric))
            if ta is not None and tb is not None and 0 < tb-ta <= 30 and value is not None and value >= 0 and (metric != "heart_rate" or value > 0) and a.get("track_segment") == b.get("track_segment"):
                pairs.append((value, tb-ta))
        if pairs and "elapsed_seconds" in result and sum(w for _, w in pairs)/result["elapsed_seconds"] >= .7:
            result[output] = round(sum(v*w for v, w in pairs)/sum(w for _, w in pairs), 1)
    return result
