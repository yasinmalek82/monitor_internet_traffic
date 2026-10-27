"""Offline measurement of monitor/worker RSS and cold/cached chart latency."""

import json
import os
import resource
import subprocess
import sys
import time
from datetime import datetime, timedelta

from iran_monitor.analysis import Assessment, Point, UTC
from iran_monitor.app import Monitor  # Include the actual monitoring imports in RSS.
from iran_monitor.chart import render_chart


def rss_mib():
    rss = subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True)
    return round(int(rss.strip()) / 1024, 2)


now = datetime.now(UTC)
points = tuple(Point(now - timedelta(minutes=15 * (96-i)), 0.2 if i > 80 else 0.8, 0.8) for i in range(96))
result = Assessment("severe", "", points)
before = rss_mib()
start = time.monotonic()
png = render_chart(result)
cold_seconds = time.monotonic() - start
after = rss_mib()
start = time.monotonic()
render_chart(result)
cached_seconds = time.monotonic() - start
child_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
child_peak_mib = child_peak / (1024**2 if sys.platform == "darwin" else 1024)
print(json.dumps({"platform": sys.platform, "monitor_rss_before_mib": before, "monitor_rss_after_mib": after,
                  "child_peak_mib": round(child_peak_mib, 2), "cold_chart_seconds": round(cold_seconds, 3),
                  "cached_chart_seconds": round(cached_seconds, 6), "png_bytes": len(png),
                  "heavy_libraries_in_monitor": [m for m in ("numpy", "matplotlib") if m in sys.modules]}, indent=2))
