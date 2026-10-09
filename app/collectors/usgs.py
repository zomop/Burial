from __future__ import annotations
import json, logging, time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from .earthquake import EarthquakeEvent
from app.config import settings

log = logging.getLogger("burial.collector")

def fetch_earthquakes() -> list[EarthquakeEvent]:
    last_error: Exception | None = None
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            request = Request(settings.feed_url, headers={"User-Agent": "BURIAL/0.1.0"})
            with urlopen(request, timeout=settings.request_timeout_seconds) as response:
                payload = json.load(response)
            events = [_parse_feature(item) for item in _feature_items(payload)]
            events = [event for event in events if event is not None]
            log.info("collection_success", extra={"event_count": len(events), "attempt": attempt})
            return events
        except (OSError, ValueError, HTTPError, URLError) as exc:
            last_error = exc
            log.warning("collection_failure", extra={"attempt": attempt, "error": str(exc)[:200]})
            if attempt < settings.retry_attempts: time.sleep(settings.retry_backoff_seconds * (2 ** (attempt - 1)))
    raise RuntimeError(f"USGS collection failed after {settings.retry_attempts} attempts: {last_error}")

def _parse_feature(item: dict) -> EarthquakeEvent | None:
    if not isinstance(item, dict):
        return None
    props = item.get("properties") or {}
    geometry = item.get("geometry") or {}
    if not isinstance(props, dict) or not isinstance(geometry, dict):
        return None
    coords = geometry.get("coordinates") or []
    if not isinstance(coords, (list, tuple)) or len(coords) < 2: return None
    timestamp = props.get("time") if isinstance(props, dict) else None
    occurred = _parse_timestamp(timestamp)
    return EarthquakeEvent("usgs", str(item.get("id") or ""), props.get("mag"), coords[2] if len(coords) > 2 else None,
        coords[1], coords[0], props.get("place") or "Unknown", occurred, props.get("url"))


def _feature_items(payload: object) -> list[object]:
    if not isinstance(payload, dict):
        raise ValueError("USGS response must be a JSON object")
    features = payload.get("features", [])
    if not isinstance(features, list):
        raise ValueError("USGS response features must be a list")
    return features


def _parse_timestamp(value: object) -> datetime | None:
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
