import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from iran_monitor.analysis import Assessment
from iran_monitor.chart import render_chart
from tests.test_analysis import assess, payload


class ResourceTests(unittest.TestCase):
    def test_monitor_stays_light_before_and_after_rendering_chart(self):
        code = """
import json, sys
from iran_monitor.app import Monitor
from iran_monitor.analysis import Assessment
from iran_monitor.chart import render_chart
before = [m for m in ('numpy', 'matplotlib') if m in sys.modules]
png = render_chart(Assessment('unknown', 'test', ()))
after = [m for m in ('numpy', 'matplotlib') if m in sys.modules]
print(json.dumps({'before': before, 'after': after, 'png': png.startswith(b'\\x89PNG')}))
"""
        process = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), {"before": [], "after": [], "png": True})

    def test_identical_chart_uses_cached_png_instead_of_starting_another_worker(self):
        render_chart.cache_clear()
        result = assess(payload())
        with patch("iran_monitor.chart.subprocess.run", wraps=subprocess.run) as run:
            first = render_chart(result)
            second = render_chart(result)
        self.assertEqual(first, second)
        self.assertEqual(run.call_count, 1)

    def test_chart_timeout_is_a_recoverable_source_error(self):
        from iran_monitor.sources import SourceError
        render_chart.cache_clear()
        with patch("iran_monitor.chart.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 60)):
            with self.assertRaises(SourceError):
                render_chart(Assessment("unknown", "timeout", ()))
