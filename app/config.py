from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    feed_url: str = os.getenv("USGS_FEED_URL", "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson")
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
    retry_backoff_seconds: float = float(os.getenv("RETRY_BACKOFF_SECONDS", "1"))
    alert_magnitude_threshold: float = float(os.getenv("ALERT_MAGNITUDE_THRESHOLD", "5.0"))
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/burial.db"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.retry_attempts < 1:
            raise ValueError("retry_attempts must be at least 1")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        if not 0 <= self.alert_magnitude_threshold <= 10:
            raise ValueError("alert_magnitude_threshold must be between 0 and 10")

settings = Settings()
