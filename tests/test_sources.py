import io
import unittest
from datetime import timedelta
from urllib.error import HTTPError
from urllib.parse import parse_qs
from unittest.mock import patch

from iran_monitor.sources import RadarClient, SourceError, fetch, parse_netblocks, parse_outages
from tests.test_analysis import NOW, payload


class SourcesTests(unittest.TestCase):
    def test_http_throttling_preserves_retry_delay_without_leaking_credentials(self):
        error = HTTPError("https://api.telegram.org/botSECRET/sendPhoto", 429, "SECRET", {},
                          io.BytesIO(b'{"parameters":{"retry_after":37},"description":"SECRET"}'))
        with patch("iran_monitor.sources.urlopen", side_effect=error):
            with self.assertRaises(SourceError) as caught:
                fetch("https://api.telegram.org/botSECRET/sendPhoto")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, 37)

    def test_radar_requests_all_four_windows_on_one_shared_scale(self):
        calls = []

        def request(url, **kwargs):
            calls.append((url, kwargs))
            return payload()

        RadarClient("secret", request).traffic(NOW)
        self.assertEqual(len(calls), 1)
        url, kwargs = calls[0]
        query = parse_qs(url.split("?", 1)[1])
        self.assertEqual(query["location"], ["IR"] * 4)
        self.assertEqual(query["name"], ["current", "week1", "week2", "week3"])
        self.assertEqual(query["normalization"], ["MIN0_MAX"])
        self.assertEqual(query["aggInterval"], ["15m"])
        self.assertEqual(query["dateEnd"][0], "2026-10-27T11:45:00Z")
        self.assertEqual(query["dateEnd"][1], "2026-10-20T11:45:00Z")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    def test_netblocks_filters_country_age_and_future_dates(self):
        def item(title, date, link="https://netblocks.org/reports/test"):
            return f"<item><title>{title}</title><description>Connectivity update</description><link>{link}</link><pubDate>{date}</pubDate></item>"

        feed = ("<rss><channel>" +
                item("Iran disruption", "Tue, 27 Oct 2026 10:00:00 +0000") +
                item("Iran old shutdown", "Tue, 20 Oct 2026 10:00:00 +0000") +
                item("Iraq disruption", "Tue, 27 Oct 2026 10:00:00 +0000") +
                item("Iran future", "Tue, 27 Oct 2027 10:00:00 +0000") +
                item("Iran unsafe link", "Tue, 27 Oct 2026 10:00:00 +0000", "https://evil.example") +
                "</channel></rss>").encode()
        reports = parse_netblocks(feed, NOW)
        self.assertEqual([r.title for r in reports], ["Iran disruption"])

    def test_netblocks_empty_feed_does_not_mean_network_is_normal(self):
        self.assertEqual(parse_netblocks(b"<rss><channel/></rss>", NOW), [])

    def test_netblocks_real_feed_has_whitespace_before_xml_declaration(self):
        self.assertEqual(parse_netblocks(b'\n<?xml version="1.0"?><rss><channel/></rss>', NOW), [])

    def test_entity_feed_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_netblocks(b'<!DOCTYPE rss [<!ENTITY x "hello">]><rss/>', NOW)

    def test_outages_only_include_iran_and_current_overlap(self):
        items = [
            {"locations": ["IR"], "startDate": (NOW-timedelta(hours=1)).isoformat(), "endDate": None, "eventType": "OUTAGE", "outage": {"outageType": "NATIONWIDE", "outageCause": "UNKNOWN"}},
            {"locations": ["US"], "startDate": (NOW-timedelta(hours=1)).isoformat(), "endDate": None, "eventType": "OUTAGE"},
            {"locations": ["IR"], "startDate": (NOW-timedelta(days=6)).isoformat(), "endDate": (NOW-timedelta(days=5)).isoformat(), "eventType": "OUTAGE"},
        ]
        self.assertEqual(len(parse_outages({"success": True, "result": {"annotations": items}}, NOW)), 1)


if __name__ == "__main__":
    unittest.main()
