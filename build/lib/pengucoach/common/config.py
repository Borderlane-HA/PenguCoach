from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PENGUCOACH_", env_file=".env", extra="ignore")

    env: str = "development"
    app_version: str = "0.1.0-alpha.3"
    database_url: str = "postgresql+asyncpg://pengucoach:pengucoach@localhost:5432/pengucoach"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "development-only-change-me"
    encryption_key: str = ""
    session_days: int = 30
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    data_dir: str = "/var/lib/pengucoach"
    garmin_default_interval_minutes: int = 30
    garmin_rate_limit_cooldown_minutes: int = 30
    ai_request_timeout_seconds: int = 120
    log_level: str = "INFO"


    @property
    def resolved_app_version(self) -> str:
        # The installed package metadata is authoritative. This also makes the
        # first update from older installers report the new version even when
        # an old PENGUCOACH_APP_VERSION value still exists in the environment.
        try:
            return package_version("pengucoach")
        except PackageNotFoundError:
            return self.app_version

    @property
    def fit_dir(self) -> Path:
        return Path(self.data_dir) / "fit"

    @property
    def parquet_dir(self) -> Path:
        return Path(self.data_dir) / "parquet"

    @property
    def backup_dir(self) -> Path:
        return Path(self.data_dir) / "backups"


@lru_cache
def get_settings() -> Settings:
    value = Settings()
    for directory in (Path(value.data_dir), value.fit_dir, value.parquet_dir, value.backup_dir):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Development/test environments can use an alternate PENGUCOACH_DATA_DIR.
            pass
    return value


settings = get_settings()
