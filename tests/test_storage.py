import tempfile
import unittest
from pathlib import Path

from iran_monitor.storage import Store, alert_kind
from tests.test_analysis import assess, payload


class AlertTests(unittest.TestCase):
    def test_repeated_severe_drop_is_silent_even_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite3"
            store = Store(path)
            result = assess(payload())
            self.assertEqual(alert_kind(result, store.get("incident", "none")), "severe")
            store.set("incident", "severe")
            store.close()
            store = Store(path)
            self.assertIsNone(alert_kind(result, store.get("incident", "none")))
            store.close()

    def test_escalation_once_and_no_repeat_on_severe_critical_oscillation(self):
        self.assertEqual(alert_kind(assess(payload((0.1,)*4)), "severe"), "critical")
        self.assertIsNone(alert_kind(assess(payload()), "critical"))
        self.assertIsNone(alert_kind(assess(payload((0.1,)*4)), "critical"))

    def test_missing_data_cannot_end_an_incident(self):
        self.assertIsNone(alert_kind(assess(payload((None,)*4)), "severe"))

    def test_recovery_alert_only_for_previously_reported_incident(self):
        recovered = assess(payload((0.8,)*4))
        self.assertEqual(alert_kind(recovered, "severe"), "recovery")
        self.assertIsNone(alert_kind(recovered, "none"))

    def test_sqlite_roundtrips_snapshot_and_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.sqlite3")
            store.set("snapshot", payload())
            store.set("telegram_offset", 123)
            self.assertEqual(store.get("snapshot")["result"]["current"]["values"][-1], 0.3)
            self.assertEqual(store.get("telegram_offset"), 123)
            self.assertEqual(store.get("missing", "fallback"), "fallback")
            store.close()


if __name__ == "__main__":
    unittest.main()
