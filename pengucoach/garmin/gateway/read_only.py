from __future__ import annotations

from datetime import date
from typing import Any

from garminconnect import Garmin


class GarminReadOnlyGateway:
    """Allow-list only facade over python-garminconnect.

    No generic ``__getattr__`` passthrough exists by design. Adding a new Garmin
    capability therefore requires an explicit code change and review.
    """

    def __init__(self, client: Garmin) -> None:
        self.__client = client

    @property
    def display_name(self) -> str | None:
        return getattr(self.__client, "display_name", None)

    def get_user_profile(self) -> dict[str, Any]:
        return self.__client.get_user_profile()

    def get_user_summary(self, day: date) -> dict[str, Any]:
        return self.__client.get_user_summary(day.isoformat())

    def get_heart_rates(self, day: date) -> dict[str, Any]:
        return self.__client.get_heart_rates(day.isoformat())

    def get_sleep_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_sleep_data(day.isoformat())

    def get_hrv_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_hrv_data(day.isoformat())

    def get_stress_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_stress_data(day.isoformat())

    def get_body_battery(self, day: date) -> list[dict[str, Any]]:
        return self.__client.get_body_battery(day.isoformat(), day.isoformat())

    def get_hydration_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_hydration_data(day.isoformat())

    def get_respiration_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_respiration_data(day.isoformat())

    def get_spo2_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_spo2_data(day.isoformat())

    def get_training_readiness(self, day: date) -> list[dict[str, Any]] | dict[str, Any]:
        return self.__client.get_training_readiness(day.isoformat())

    def get_training_status(self, day: date) -> dict[str, Any]:
        return self.__client.get_training_status(day.isoformat())

    def get_max_metrics(self, day: date) -> Any:
        return self.__client.get_max_metrics(day.isoformat())

    def get_intensity_minutes_data(self, day: date) -> dict[str, Any]:
        return self.__client.get_intensity_minutes_data(day.isoformat())

    def get_floors(self, day: date) -> dict[str, Any]:
        return self.__client.get_floors(day.isoformat())

    def get_stats_and_body(self, day: date) -> dict[str, Any]:
        return self.__client.get_stats_and_body(day.isoformat())

    def get_body_composition(self, start: date, end: date) -> Any:
        return self.__client.get_body_composition(start.isoformat(), end.isoformat())

    def get_weigh_ins(self, start: date, end: date) -> Any:
        return self.__client.get_weigh_ins(start.isoformat(), end.isoformat())

    def get_blood_pressure(self, start: date, end: date) -> Any:
        return self.__client.get_blood_pressure(start.isoformat(), end.isoformat())

    def get_endurance_score(self, start: date, end: date) -> Any:
        return self.__client.get_endurance_score(start.isoformat(), end.isoformat())

    def get_hill_score(self, start: date, end: date) -> Any:
        return self.__client.get_hill_score(start.isoformat(), end.isoformat())

    def get_race_predictions(self) -> Any:
        return self.__client.get_race_predictions()

    def count_activities(self) -> int:
        return int(self.__client.count_activities())

    def get_activities_page(self, start: int = 0, limit: int = 1000) -> Any:
        return self.__client.get_activities(start=start, limit=limit)

    def get_activities_by_date(self, start: date, end: date) -> list[dict[str, Any]]:
        return self.__client.get_activities_by_date(start.isoformat(), end.isoformat())

    def get_activity(self, activity_id: int) -> dict[str, Any]:
        return self.__client.get_activity(activity_id)

    def get_activity_details(self, activity_id: int) -> dict[str, Any]:
        return self.__client.get_activity_details(activity_id)

    def get_activity_splits(self, activity_id: int) -> Any:
        method = getattr(self.__client, "get_activity_splits", None)
        return method(activity_id) if method else None

    def get_activity_weather(self, activity_id: int) -> Any:
        method = getattr(self.__client, "get_activity_weather", None)
        return method(activity_id) if method else None

    def get_activity_gear(self, activity_id: int) -> Any:
        return self.__client.get_activity_gear(activity_id)

    def get_devices(self) -> Any:
        return self.__client.get_devices()

    def get_gear(self) -> Any:
        return self.__client.get_gear()

    def download_activity_fit(self, activity_id: int) -> bytes:
        # Garmin ORIGINAL is normally a zip containing the FIT file.
        return self.__client.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
