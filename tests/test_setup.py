import tempfile
import unittest
from pathlib import Path

from iran_monitor.config import Config, load_env
from iran_monitor.setup import configure


class SetupTests(unittest.TestCase):
    def test_setup_saves_valid_credentials_privately_and_does_not_echo_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.env"
            answers = iter(("123:private-token", "radar-private-token"))
            messages = []
            configure(path, secret=lambda label: next(answers), ask=lambda label: "42", tell=messages.append)
            values = load_env(path, {})
            config = Config.from_values(values)
            self.assertEqual(config.chat_id, 42)
            self.assertEqual(config.poll_seconds, 300)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("private-token", " ".join(messages))

    def test_failed_configuration_keeps_previous_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.env"
            original = "TELEGRAM_BOT_TOKEN=123:old\nTELEGRAM_CHAT_ID=42\nCLOUDFLARE_API_TOKEN=old\n"
            path.write_text(original)
            with self.assertRaises(ValueError):
                configure(path, secret=lambda label: "", ask=lambda label: "bad", tell=lambda message: None)
            self.assertEqual(path.read_text(), original)

    def test_enter_preserves_existing_credentials_and_poll_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.env"
            path.write_text("TELEGRAM_BOT_TOKEN=123:old\nTELEGRAM_CHAT_ID=42\nCLOUDFLARE_API_TOKEN=old\nPOLL_SECONDS=600\n")
            configure(path, secret=lambda label: "", ask=lambda label: "", tell=lambda message: None)
            self.assertEqual(Config.from_values(load_env(path, {})).poll_seconds, 600)

    def test_setup_rejects_multiline_token_instead_of_injecting_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.env"
            with self.assertRaises(ValueError):
                configure(path, secret=lambda label: "123:x\nPOLL_SECONDS=1", ask=lambda label: "42", tell=lambda message: None)
            self.assertFalse(path.exists())
