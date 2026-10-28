from datetime import datetime, timedelta, timezone

import pandas as pd

from pengucoach.fit.activity_detail import build_activity_stats, build_distance_splits, serialize_series, sport_family


def sample_frame() -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(0, 121):
        rows.append({
            "timestamp": (start + timedelta(seconds=i)).isoformat(),
            "distance": i * 10.0,
            "heart_rate": 120 + (i % 20),
            "enhanced_speed": 10.0,
            "power": 180 + (i % 30),
            "cadence": 82 + (i % 5),
            "enhanced_altitude": 400 + i * 0.1,
            "temperature": 20.0,
        })
    return pd.DataFrame(rows)


def test_sport_family():
    assert sport_family("road_biking") == "bike"
    assert sport_family("trail_running") == "run"
    assert sport_family("lap_swimming") == "swim"
    assert sport_family("strength_training") == "strength"


def test_activity_stats_are_deterministic():
    stats = build_activity_stats(sample_frame(), "road_biking")
    assert stats["records"] == 121
    assert stats["sport_family"] == "bike"
    assert stats["heart_rate"]["min"] == 120
    assert stats["heart_rate"]["max"] == 139
    assert stats["speed_kmh"]["avg"] == 36.0
    assert stats["power_w"]["normalized"] is not None
    assert stats["elevation"]["gain_m"] is not None
    assert stats["coverage"]["power"] == 100.0


def test_kilometre_splits():
    splits = build_distance_splits(sample_frame(), "road_biking")
    assert len(splits) == 2
    assert splits[0]["index"] == 1
    assert splits[0]["elapsed_s"] > 0
    assert splits[0]["avg_hr"] is not None


def test_serialized_series_contains_normalized_channels():
    data = serialize_series(sample_frame(), limit=25)
    assert len(data) == 25
    assert "elapsed_s" in data[0]
    assert "speed_kmh" in data[0]
    assert "altitude_m" in data[0]
    assert "grade_pct" in data[0]
