import sys
import types
from pathlib import Path


def _load_module():
    try:
        import garminconnect  # noqa: F401
    except ImportError:
        stub = types.ModuleType("garminconnect")
        stub.Garmin = type("Garmin", (), {})
        stub.GarminConnectAuthenticationError = type("GarminConnectAuthenticationError", (Exception,), {})
        stub.GarminConnectTooManyRequestsError = type("GarminConnectTooManyRequestsError", (Exception,), {})
        sys.modules["garminconnect"] = stub
    from pengucoach.garmin.zones import normalize_heart_rate_zones, normalize_power_zones
    return normalize_heart_rate_zones, normalize_power_zones


def test_hr_zone_profiles_keep_garmin_boundaries():
    hr, _ = _load_module()
    profiles = hr([{
        "sport": "CYCLING",
        "maxHeartRateUsed": 190,
        "zone1Floor": 95,
        "zone2Floor": 115,
        "zone3Floor": 135,
        "zone4Floor": 155,
        "zone5Floor": 175,
    }])
    assert profiles[0]["sport"] == "CYCLING"
    assert profiles[0]["zones"][1] == {"zone": 2, "low_bpm": 115, "high_bpm": 134}
    assert profiles[0]["zones"][-1]["high_bpm"] == 190


def test_power_zone_profiles_accept_zone_arrays():
    _, power = _load_module()
    profiles = power([{
        "sport": "CYCLING",
        "functionalThresholdPower": 250,
        "powerZones": [
            {"zoneNumber": 1, "zoneLowBoundary": 0, "zoneHighBoundary": 137},
            {"zoneNumber": 2, "zoneLowBoundary": 138, "zoneHighBoundary": 187},
        ],
    }])
    assert profiles[0]["ftp_w"] == 250
    assert profiles[0]["zones"][1]["low_w"] == 138


def test_ai_prompts_and_context_include_training_zones():
    context = Path("pengucoach/coach/context.py").read_text()
    service = Path("pengucoach/llm/service.py").read_text()
    gateway = Path("pengucoach/garmin/gateway/read_only.py").read_text()
    assert '"training_zones": zones' in context
    assert '"time_in_zones": zone_time' in context
    assert "training_zones" in service
    assert "get_heart_rate_zones" in gateway and "get_power_zones" in gateway


def test_ios_number_inputs_do_not_use_incompatible_steps():
    for filename in (
        "apps/web/app/training/page.tsx",
        "apps/web/app/coach/page.tsx",
        "apps/web/app/activities/[id]/page.tsx",
        "apps/web/app/admin/ai/page.tsx",
    ):
        text = Path(filename).read_text()
        assert 'min={128}' not in text or 'min={128}' in text and 'step={100}' not in text and 'step={250}' not in text
