import os, sqlite3, subprocess, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
class BurialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); os.environ["DATABASE_PATH"]=str(Path(self.tmp.name)/"test.db")
        import importlib; import app.config; importlib.reload(app.config)
        import app.database.sqlite as sql; importlib.reload(sql); sql.initialize_database()
    def tearDown(self): self.tmp.cleanup()
    def event(self, **kw):
        from app.collectors.earthquake import EarthquakeEvent
        values=dict(source="USGS",source_event_id="abc",magnitude=5.5,depth_km=10,latitude=1,longitude=2,location="  Test   place ",occurred_at=datetime.now(timezone.utc),source_url="https://example")
        values.update(kw); return EarthquakeEvent(**values)
    def test_validation_and_normalization(self):
        from app.collectors.validation import validate_earthquake
        from app.collectors.normalization import normalize_earthquake
        e=self.event(); self.assertEqual(validate_earthquake(e), []); n=normalize_earthquake(e); self.assertEqual(n.source,"usgs"); self.assertEqual(n.location,"Test place")

    def test_normalization_assigns_utc_to_naive_timestamp(self):
        from app.collectors.normalization import normalize_earthquake
        event = normalize_earthquake(self.event(occurred_at=datetime(2026, 1, 1), source_url="  https://example  "))
        self.assertEqual(event.occurred_at.tzinfo, timezone.utc)
        self.assertEqual(event.source_url, "https://example")

    def test_discord_alert_reports_missing_webhook(self):
        from app.alerts.discord import send_alert
        success, error = send_alert({"magnitude": 5.0, "location": "Test", "occurred_at": "now", "id": 1})
        self.assertFalse(success)
        self.assertIn("not configured", error)
    def test_malformed_numeric_input_is_rejected(self):
        from app.collectors.validation import validate_earthquake
        errors=validate_earthquake(self.event(magnitude="not-a-number", latitude="bad"))
        self.assertIn("missing or non-finite magnitude", errors); self.assertIn("latitude outside valid range", errors)
    def test_atomic_deduplication(self):
        from app.database.events import save_event
        e=self.event(); self.assertIsNotNone(save_event(e)); self.assertIsNone(save_event(e))
    def test_alert_threshold_is_configurable(self):
        import app.config; app.config.settings=app.config.Settings(alert_magnitude_threshold=6.0)
        from app.database.events import save_event
        from app.alerts.engine import evaluate_and_alert
        event_id=save_event(self.event()); self.assertFalse(evaluate_and_alert(event_id))
    def test_health_has_database(self):
        from app.monitoring.health import health_status
        self.assertEqual(health_status()["database"],"connected")

    def test_health_includes_collection_metadata(self):
        from app.monitoring.health import health_status
        status = health_status(last_collection="2026-10-08T00:00:00+00:00", collector="usgs")
        self.assertEqual(status["collector"], "usgs")
        self.assertEqual(status["last_successful_collection"], "2026-10-08T00:00:00+00:00")
        self.assertIn("checked_at", status)

    def test_invalid_settings_are_rejected(self):
        from app.config import Settings
        with self.assertRaisesRegex(ValueError, "poll_interval_seconds"):
            Settings(poll_interval_seconds=0)
        with self.assertRaisesRegex(ValueError, "retry_attempts"):
            Settings(retry_attempts=0)
        with self.assertRaisesRegex(ValueError, "alert_magnitude_threshold"):
            Settings(alert_magnitude_threshold=11)

    def test_boolean_settings_are_rejected(self):
        from app.config import Settings
        for field in ("poll_interval_seconds", "request_timeout_seconds", "retry_attempts", "retry_backoff_seconds", "alert_magnitude_threshold"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    Settings(**{field: True})

    def test_usgs_parser_skips_invalid_records(self):
        from app.collectors.usgs import _parse_feature
        self.assertIsNone(_parse_feature("not-an-object"))
        self.assertIsNone(_parse_feature({"geometry": {"coordinates": [1]}}))
        self.assertIsNone(_parse_feature({"properties": "bad", "geometry": {}}))
        self.assertIsNone(_parse_feature({"properties": {}, "geometry": "bad"}))

    def test_usgs_parser_keeps_event_with_invalid_timestamp_for_validation(self):
        from app.collectors.usgs import _parse_feature
        event = _parse_feature({
            "id": "evt-1",
            "properties": {"mag": 4.2, "time": "invalid", "place": "Test"},
            "geometry": {"coordinates": [2, 1, 10]},
        })
        self.assertIsNotNone(event)
        self.assertIsNone(event.occurred_at)

    def test_usgs_parser_converts_epoch_milliseconds_to_utc(self):
        from app.collectors.usgs import _parse_timestamp
        parsed = _parse_timestamp(0)
        self.assertEqual(parsed, datetime(1970, 1, 1, tzinfo=timezone.utc))

    def test_usgs_payload_requires_feature_list(self):
        from app.collectors.usgs import _feature_items
        with self.assertRaisesRegex(ValueError, "JSON object"):
            _feature_items([])
        with self.assertRaisesRegex(ValueError, "features must be a list"):
            _feature_items({"features": {}})

    def test_sqlite_enforces_alert_event_reference(self):
        from app.database.sqlite import get_connection
        with self.assertRaises(sqlite3.IntegrityError):
            with get_connection() as db:
                db.execute("INSERT INTO alerts(event_id, channel, status, created_at) VALUES (?,?,?,?)", (999, "discord", "pending", "now"))

    def test_sqlite_creates_operational_indexes(self):
        from app.database.sqlite import get_connection
        with get_connection() as db:
            indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_events_occurred_at", indexes)
        self.assertIn("idx_alerts_status", indexes)

    def test_cli_exposes_version(self):
        result = subprocess.run([sys.executable, "main.py", "--version"], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "BURIAL 0.1.0")

    def test_event_severity_boundaries(self):
        self.assertEqual(self.event(magnitude=4.9).severity, "low")
        self.assertEqual(self.event(magnitude=5.0).severity, "moderate")
        self.assertEqual(self.event(magnitude=6.0).severity, "high")
        self.assertEqual(self.event(magnitude=7.0).severity, "critical")

    def test_validator_accepts_inclusive_geospatial_boundaries(self):
        from app.collectors.validation import validate_earthquake
        self.assertEqual(validate_earthquake(self.event(magnitude=-2, latitude=-90, longitude=-180)), [])
        self.assertEqual(validate_earthquake(self.event(magnitude=10, latitude=90, longitude=180)), [])

    def test_validator_rejects_boolean_measurements(self):
        from app.collectors.validation import validate_earthquake
        errors = validate_earthquake(self.event(magnitude=True, latitude=False))
        self.assertIn("missing or non-finite magnitude", errors)
        self.assertIn("latitude outside valid range", errors)
if __name__ == "__main__": unittest.main()
