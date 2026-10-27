import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from iran_monitor.config import Config, load_env
from iran_monitor.reporting import report_text
from iran_monitor.sources import SourceError
from iran_monitor.analysis import analyze, parse_radar
from iran_monitor.telegram import TelegramClient, TelegramError, authorized_command
from tests.test_analysis import NOW, assess, payload


class BotTests(unittest.TestCase):
    def test_telegram_http_failure_retains_status_for_retry_and_fatal_handling(self):
        def request(*args, **kwargs):
            raise SourceError("Remote HTTP error 429", status=429, retry_after=37)
        client = TelegramClient("123:secret", 42, request)
        with self.assertRaises(TelegramError) as caught:
            client.message("test")
        self.assertEqual(caught.exception.code, 429)
        self.assertEqual(caught.exception.retry_after, 37)

    def test_only_owner_private_chat_can_request_reports(self):
        def update(chat_id, text="/chart", chat_type="private"):
            return {"message": {"chat": {"id": chat_id, "type": chat_type}, "text": text}}

        self.assertEqual(authorized_command(update(42), 42), "chart")
        self.assertIsNone(authorized_command(update(43), 42))
        self.assertIsNone(authorized_command(update(42, chat_type="group"), 42))
        self.assertIsNone(authorized_command({"edited_message": update(42)["message"]}, 42))
        self.assertEqual(authorized_command(update(42, "/status@mybot"), 42), "status")

    def test_blank_and_noncommand_updates_do_not_crash(self):
        for text in ("", " ", "سلام", None):
            self.assertIsNone(authorized_command({"message": {"chat": {"id": 42, "type": "private"}, "text": text}}, 42))

    def test_telegram_uses_fixed_owner_destination_and_uploads_png(self):
        calls = []

        def request(url, **kwargs):
            calls.append((url, kwargs))
            return {"ok": True, "result": {"message_id": 7}}

        client = TelegramClient("123:secret", 42, request)
        client.photo(b"\x89PNG\r\n\x1a\nFAKE", "توضیح فارسی")
        url, kwargs = calls[0]
        self.assertTrue(url.endswith("/sendPhoto"))
        self.assertIn(b'filename="traffic.png"', kwargs["data"])
        self.assertIn(b'42', kwargs["data"])
        self.assertIn("توضیح فارسی".encode(), kwargs["data"])

    def test_telegram_application_error_is_not_success(self):
        client = TelegramClient("123:secret", 42, lambda *a, **k: {"ok": False, "error_code": 429, "parameters": {"retry_after": 20}})
        with self.assertRaisesRegex(RuntimeError, "429"):
            client.message("test")

    def test_persian_report_quantifies_drop_without_claiming_censorship(self):
        text = report_text(assess(payload()), NOW, [], [], [])
        self.assertIn("۶۲", text)
        self.assertIn("۳۰", text)
        self.assertIn("تهران", text)
        self.assertIn("علت", text)
        self.assertIn("Cloudflare", text)
        self.assertIn("NetBlocks", text)
        self.assertLessEqual(len(text), 1024)

    def test_unknown_report_does_not_claim_current_drop(self):
        text = report_text(assess(payload((None,)*4)), NOW, [], [], [])
        self.assertIn("نامشخص", text)
        self.assertNotIn("۶۲", text)

    def test_stale_report_shows_last_known_drop_and_exact_age(self):
        now = NOW + timedelta(minutes=60)
        result = analyze(parse_radar(payload()), now)
        text = report_text(result, now, [], [], [], checked_at=now, fetched_at=now)
        self.assertIn("۶۲", text)
        self.assertIn("۷۵ دقیقه", text)
        self.assertIn("در آن زمان", text)
        self.assertIn("پاسخ", text)
        self.assertNotIn("🟢", text)
        self.assertNotIn("۴۸ ساعت", text)

    def test_normal_report_leads_with_plain_usable_conclusion(self):
        text = report_text(assess(payload((0.8,)*4)), NOW, [], [], [])
        self.assertIn("روال", text)
        self.assertNotIn("۰٪ کمتر", text)
        self.assertNotIn("NetBlocks", text)


    def test_env_is_data_not_executable_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("TELEGRAM_BOT_TOKEN='123:abc'\nTELEGRAM_CHAT_ID=42\nCLOUDFLARE_API_TOKEN=$(touch /tmp/should-not-run)\n", encoding="utf-8")
            values = load_env(path, {})
            self.assertEqual(values["CLOUDFLARE_API_TOKEN"], "$(touch /tmp/should-not-run)")
            self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "123:abc")

    def test_environment_takes_precedence_over_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("TELEGRAM_CHAT_ID=123\n")
            self.assertEqual(load_env(path, {"TELEGRAM_CHAT_ID": "42"})["TELEGRAM_CHAT_ID"], "42")

    def test_invalid_or_missing_configuration_fails_closed(self):
        for values in ({}, {"TELEGRAM_BOT_TOKEN": "123:x", "TELEGRAM_CHAT_ID": "-100", "CLOUDFLARE_API_TOKEN": "x"},
                       {"TELEGRAM_BOT_TOKEN": "123:x", "TELEGRAM_CHAT_ID": "42", "CLOUDFLARE_API_TOKEN": "x", "POLL_SECONDS": "0"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Config.from_values(values)


if __name__ == "__main__":
    unittest.main()
