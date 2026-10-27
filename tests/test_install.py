import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_dry_run_explains_install_without_root_downloads_or_mutations(self):
        result = subprocess.run(["bash", str(ROOT / "install.sh"), "--dry-run", "--ref", "v0.1.0"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("v0.1.0", result.stdout)
        self.assertIn("256M", result.stdout)
        self.assertIn("20%", result.stdout)
        self.assertIn("/opt/iran-internet-monitor", result.stdout)

    def test_invalid_ref_is_rejected_before_commands_run(self):
        result = subprocess.run(["bash", str(ROOT / "install.sh"), "--dry-run", "--ref", "main; printf BAD"],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BAD", result.stdout)

    def test_management_status_touches_only_its_own_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "systemctl"
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            fake.chmod(0o755)
            result = subprocess.run(["bash", str(ROOT / "deploy/iran-monitor"), "status"],
                                    env={**os.environ, "PATH": tmp + ":" + os.environ["PATH"]},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["status", "iran-internet-monitor.service", "--no-pager"])
