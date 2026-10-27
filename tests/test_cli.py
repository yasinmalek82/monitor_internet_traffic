import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def test_demo_generates_png_and_persian_report_without_any_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, "-m", "iran_monitor", "demo", "--output", tmp],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(tmp) / "demo.png").read_bytes().startswith(b"\x89PNG"))
            self.assertIn("ساختگی", (Path(tmp) / "demo-report.txt").read_text())

    def test_missing_credentials_give_actionable_error_without_starting_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TELEGRAM_", "CLOUDFLARE_"))}
            result = subprocess.run([sys.executable, "-m", "iran_monitor", "--env", tmp + "/missing", "check"],
                                    capture_output=True, text=True, env=env, timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertIn("TELEGRAM_BOT_TOKEN", result.stderr)


if __name__ == "__main__":
    unittest.main()
