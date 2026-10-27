import unittest
from datetime import datetime, timedelta, timezone

from iran_monitor.analysis import analyze, comparison_points, parse_radar

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def payload(values=(0.8, 0.8, 0.3, 0.3), baseline=(0.8, 0.8, 0.8, 0.8)):
    times = [NOW - timedelta(minutes=75 - i * 15) for i in range(len(values))]
    result = {
        "meta": {"normalization": "MIN0_MAX", "aggInterval": "FIFTEEN_MINUTES",
                 "confidenceInfo": {"level": 5}, "lastUpdated": NOW.isoformat()},
        "current": {"timestamps": [t.isoformat() for t in times], "values": list(values)},
    }
    for week in (1, 2, 3):
        result[f"week{week}"] = {
            "timestamps": [(t - timedelta(weeks=week)).isoformat() for t in times],
            "values": list(baseline),
        }
    return {"success": True, "result": result}


def assess(data):
    return analyze(parse_radar(data), NOW)


class AnalysisTests(unittest.TestCase):
    def test_sustained_drop_uses_same_time_in_prior_weeks(self):
        result = assess(payload())
        self.assertEqual(result.status, "severe")
        self.assertAlmostEqual(result.drop_percent, 62.5)
        self.assertEqual(result.duration_minutes, 30)

    def test_one_bad_bucket_does_not_trigger_severe_alert(self):
        self.assertEqual(assess(payload((0.8, 0.8, 0.8, 0.05))).status, "watch")

    def test_critical_requires_two_critical_buckets(self):
        self.assertEqual(assess(payload((0.8, 0.3, 0.1, 0.1))).status, "critical")
        self.assertEqual(assess(payload((0.8, 0.8, 0.3, 0.1))).status, "severe")

    def test_nightly_drop_matches_nightly_baseline(self):
        self.assertEqual(assess(payload((0.8, 0.6, 0.3, 0.2), (0.8, 0.6, 0.3, 0.2))).status, "normal")

    def test_single_abnormal_historical_week_does_not_skew_baseline(self):
        data = payload()
        data["result"]["week1"]["values"] = [0.01] * 4
        self.assertEqual(assess(data).status, "severe")

    def test_stale_data_cannot_be_called_healthy_or_recovered(self):
        data = parse_radar(payload())
        self.assertEqual(analyze(data, NOW + timedelta(hours=3)).status, "unknown")

    def test_stale_valid_data_retains_a_separate_last_known_analysis(self):
        result = analyze(parse_radar(payload()), NOW + timedelta(minutes=60))
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.historical_status, "severe")
        self.assertAlmostEqual(result.drop_percent, 62.5)
        self.assertEqual(result.duration_minutes, 30)
        self.assertFalse(result.recovery_ready)

    def test_stale_bad_quality_data_does_not_gain_a_historical_conclusion(self):
        data = payload()
        data["result"]["meta"]["confidenceInfo"]["level"] = 2
        result = analyze(parse_radar(data), NOW + timedelta(hours=3))
        self.assertIsNone(result.historical_status)
        self.assertIsNone(result.drop_percent)

    def test_low_source_confidence_suppresses_alert(self):
        data = payload()
        data["result"]["meta"]["confidenceInfo"]["level"] = 3
        self.assertEqual(assess(data).status, "unknown")

    def test_missing_confidence_is_reported_as_unknown(self):
        data = payload()
        del data["result"]["meta"]["confidenceInfo"]
        self.assertEqual(assess(data).status, "unknown")

    def test_missing_current_bucket_is_not_zero_or_skipped(self):
        data = payload((0.8, 0.8, 0.1, None))
        self.assertEqual(assess(data).status, "unknown")

    def test_empty_source_is_unknown(self):
        self.assertEqual(assess(payload((), ())).status, "unknown")

    def test_zero_reference_is_not_a_blackout(self):
        self.assertEqual(assess(payload(baseline=(0, 0, 0, 0))).status, "unknown")

    def test_two_reference_weeks_required(self):
        data = payload()
        for week in (1, 2):
            data["result"][f"week{week}"]["values"] = [None] * 4
        self.assertEqual(assess(data).status, "unknown")

    def test_reference_alignment_uses_timestamps_not_array_positions(self):
        data = payload()
        for week in (1, 2, 3):
            data["result"][f"week{week}"]["timestamps"].reverse()
            data["result"][f"week{week}"]["values"] = [0.8, 0.8, 0.5, 0.5]
        points = comparison_points(parse_radar(data))
        self.assertEqual([p.baseline for p in points], [0.5, 0.5, 0.8, 0.8])

    def test_gap_between_bad_buckets_is_not_sustained_drop(self):
        data = payload((0.8, 0.1, 0.1, 0.1))
        data["result"]["current"]["timestamps"].pop(-2)
        data["result"]["current"]["values"].pop(-2)
        self.assertEqual(assess(data).status, "unknown")

    def test_incomplete_bucket_does_not_trigger_alert(self):
        data = payload((0.8, 0.8, 0.8, 0.1))
        data["result"]["current"]["timestamps"][-1] = (NOW - timedelta(minutes=5)).isoformat()
        self.assertEqual(assess(data).status, "normal")

    def test_recovery_requires_two_good_buckets(self):
        result = assess(payload((0.1, 0.1, 0.8, 0.8)))
        self.assertTrue(result.recovery_ready)
        self.assertFalse(assess(payload((0.1, 0.1, 0.1, 0.8))).recovery_ready)

    def test_nonfinite_values_and_negative_values_are_missing(self):
        for value in ("NaN", "inf", -0.1, "unavailable"):
            with self.subTest(value=value):
                self.assertEqual(assess(payload((0.8, 0.8, 0.1, value))).status, "unknown")

    def test_minmax_with_nonzero_minimum_cannot_support_drop_percentages(self):
        data = payload()
        data["result"]["meta"]["normalization"] = "MIN_MAX"
        with self.assertRaises(ValueError):
            parse_radar(data)

    def test_bad_api_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_radar({"success": False, "errors": [{"message": "bad token"}]})

    def test_mismatched_timestamp_value_arrays_rejected(self):
        data = payload()
        data["result"]["current"]["values"].pop()
        with self.assertRaises(ValueError):
            parse_radar(data)

    def test_confidence_metadata_annotations_suppress_affected_bins(self):
        data = payload()
        data["result"]["meta"]["confidenceInfo"]["annotations"] = [{
            "eventType": "PIPELINE", "startDate": (NOW - timedelta(hours=1)).isoformat(),
            "endDate": None, "description": "Data pipeline incident"}]
        self.assertEqual(assess(data).status, "unknown")


if __name__ == "__main__":
    unittest.main()
