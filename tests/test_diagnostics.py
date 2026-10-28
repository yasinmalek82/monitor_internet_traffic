import contextlib
import io
import unittest
from unittest.mock import patch

from iran_monitor.__main__ import diagnose
from iran_monitor.config import Config
from iran_monitor.sources import RadarClient, SourceError
from tests.test_analysis import NOW, payload


def telegram_result(method, params=None):
    return {"getMe": {"id": 123, "is_bot": True, "username": "RadarExampleBot"},
            "getWebhookInfo": {"url": "", "pending_update_count": 0},
            "getChat": {"id": 42, "type": "private"}}[method]


class DiagnosticTests(unittest.TestCase):
    def test_live_diagnose_reports_timestamps_without_echoing_credentials(self):
        output = io.StringIO()
        with patch("iran_monitor.__main__.TelegramClient.call", side_effect=telegram_result), \
             patch.object(RadarClient, "traffic", return_value=payload()), contextlib.redirect_stdout(output):
            code = diagnose(Config("123:private-telegram", 42, "private-cloudflare"), now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("UTC 2026-10-27T12:00", output.getvalue())
        self.assertIn("آخرین دریافت موفق", output.getvalue())
        self.assertNotIn("private-", output.getvalue())
        self.assertIn("@RadarExampleBot", output.getvalue())

    def test_diagnose_distinguishes_access_failure_from_missing_traffic(self):
        output = io.StringIO()
        with patch("iran_monitor.__main__.TelegramClient.call", side_effect=telegram_result), \
             patch.object(RadarClient, "traffic", side_effect=SourceError("hidden", status=403)), contextlib.redirect_stdout(output):
            code = diagnose(Config("123:private-telegram", 42, "private-cloudflare"), now=NOW)
        self.assertEqual(code, 2)
        self.assertIn("HTTP 403", output.getvalue())
        self.assertNotIn("private-", output.getvalue())

    def test_diagnose_identifies_telegram_auth_failure_without_polling(self):
        from iran_monitor.telegram import TelegramError
        output = io.StringIO()
        with patch("iran_monitor.__main__.TelegramClient.call", side_effect=TelegramError(401)), contextlib.redirect_stdout(output):
            code = diagnose(Config("123:private-telegram", 42, "private-cloudflare"), now=NOW)
        self.assertEqual(code, 2)
        self.assertIn("Telegram", output.getvalue())
        self.assertIn("401", output.getvalue())
        self.assertNotIn("private-", output.getvalue())
