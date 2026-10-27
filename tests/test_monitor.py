import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from iran_monitor.app import Monitor
from iran_monitor.config import Config
from iran_monitor.sources import SourceError
from iran_monitor.storage import Store
from tests.test_analysis import NOW, payload


class FakeRadar:
    def __init__(self):
        self.data = payload()
        self.fail = False
        self.calls = 0

    def traffic(self, now):
        self.calls += 1
        if self.fail:
            raise SourceError("network failure")
        return self.data

    def outages(self, now):
        return []


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.fail = False

    def photo(self, png, caption):
        if self.fail:
            raise SourceError("delivery failure")
        self.sent.append((png, caption))

    def message(self, text):
        if self.fail:
            raise SourceError("delivery failure")
        self.sent.append((None, text))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.sqlite3")
        self.radar = FakeRadar()
        self.telegram = FakeTelegram()
        self.monitor = Monitor(Config("123:test", 42, "test"), self.store, self.radar,
                               self.telegram, lambda now: [], lambda *a, **k: b"PNG")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_failed_delivery_keeps_incident_pending_and_retries(self):
        self.telegram.fail = True
        with self.assertRaises(SourceError):
            self.monitor.refresh(NOW)
        self.assertEqual(self.store.get("incident", "none"), "none")
        self.telegram.fail = False
        self.monitor.refresh(NOW)
        self.assertEqual(self.store.get("incident"), "severe")
        self.assertEqual(len(self.telegram.sent), 1)
        self.monitor.refresh(NOW)
        self.assertEqual(len(self.telegram.sent), 1)

    def test_source_failure_does_not_send_recovery(self):
        self.monitor.refresh(NOW)
        self.radar.fail = True
        with self.assertLogs("iran_monitor.app", level="WARNING"):
            for _ in range(3):
                self.monitor.refresh(NOW)
        self.assertEqual(self.store.get("incident"), "severe")
        self.assertEqual(len(self.telegram.sent), 2)
        self.assertIn("نامشخص", self.telegram.sent[-1][1])

    def test_auxiliary_source_failure_does_not_block_severe_alert(self):
        def unavailable(now):
            raise SourceError("unavailable")
        self.monitor.netblocks = unavailable
        self.monitor.refresh(NOW)
        self.assertEqual(self.store.get("incident"), "severe")
        self.assertIn("دریافت گزارش ممکن نشد", self.telegram.sent[-1][1])

    def test_chart_failure_still_delivers_text_alert(self):
        def unavailable(*args, **kwargs):
            raise SourceError("Chart worker exceeded limit")
        self.monitor.chart = unavailable
        with self.assertLogs("iran_monitor.app", level="WARNING"):
            self.monitor.refresh(NOW)
        self.assertEqual(self.store.get("incident"), "severe")
        self.assertIsNone(self.telegram.sent[-1][0])
        self.assertIn("افت شدید", self.telegram.sent[-1][1])
        self.assertIn("نمودار", self.telegram.sent[-1][1])

    def test_status_recomputes_freshness_instead_of_showing_cached_green(self):
        self.radar.data = payload((0.8,)*4)
        self.monitor.refresh(NOW)
        result, _, _, _ = self.monitor.current(NOW + timedelta(hours=3))
        self.assertEqual(result.status, "unknown")

    def test_status_retries_stale_source_and_keeps_repeated_commands_bounded(self):
        now = NOW + timedelta(hours=3)
        self.monitor.refresh(now)
        owner = {"message": {"chat": {"id": 42, "type": "private"}, "text": "/status"}}
        self.monitor.handle(owner, now + timedelta(seconds=65))
        self.monitor.handle(owner, now + timedelta(seconds=70))
        self.assertEqual(self.radar.calls, 2)
        self.assertIn("در آن زمان", self.telegram.sent[-1][1])
        self.assertEqual(self.store.get("unknown_count"), 1)

    def test_failed_fetch_preserves_last_known_numeric_analysis(self):
        self.monitor.refresh(NOW)
        self.radar.fail = True
        with self.assertLogs("iran_monitor.app", level="WARNING"):
            self.monitor.refresh(NOW + timedelta(minutes=5))
        result, _, _, _ = self.monitor.current(NOW + timedelta(minutes=5))
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.historical_status, "severe")
        self.assertAlmostEqual(result.drop_percent, 62.5)

    def test_private_diagnostics_include_fetch_and_data_times_without_secrets(self):
        self.monitor.refresh(NOW)
        self.monitor.handle({"message": {"chat": {"id": 42, "type": "private"}, "text": "/diagnostics"}}, NOW)
        text = self.telegram.sent[-1][1]
        self.assertIn("آخرین دریافت موفق", text)
        self.assertIn("UTC", text)
        self.assertIn("2026-10-27T12:00", text)
        self.assertNotIn("123:test", text)


    def test_unauthorized_command_has_no_outbound_side_effect(self):
        self.monitor.handle({"update_id": 1, "message": {"chat": {"id": 99, "type": "private"}, "text": "/chart"}}, NOW)
        self.assertEqual(self.telegram.sent, [])

    def test_owner_receives_persian_report_and_chart(self):
        self.radar.data = payload((0.8,)*4)
        self.monitor.refresh(NOW)
        self.monitor.handle({"message": {"chat": {"id": 42, "type": "private"}, "text": "/chart"}}, NOW)
        self.assertEqual(self.telegram.sent[-1][0], b"PNG")
        self.assertIn("ترافیک", self.telegram.sent[-1][1])

    def test_recovery_is_sent_once_and_history_records_delivered_events(self):
        self.monitor.refresh(NOW)
        self.radar.data = payload((0.8,)*4)
        self.monitor.refresh(NOW)
        self.monitor.refresh(NOW)
        self.assertEqual(len(self.telegram.sent), 2)
        self.assertEqual(self.store.get("incident"), "none")
        self.assertEqual([e["kind"] for e in self.store.get("history")], ["severe", "recovery"])


if __name__ == "__main__":
    unittest.main()
