"""One bounded worker for slow source/plot operations; polling stays responsive."""

import logging
import queue
import threading
import time
from datetime import datetime

from .analysis import UTC
from .app import Monitor
from .chart import render_chart
from .reporting import report_text
from .sources import RadarClient, SourceError, netblocks_reports
from .storage import Store
from .telegram import TelegramError, authorized_command

LOG = logging.getLogger(__name__)


def process_updates(monitor, store, updates, *, now=lambda: datetime.now(UTC), stop=None):
    for update in updates:
        if stop is not None and stop.is_set():
            break
        try:
            monitor.handle(update, now())
        except TelegramError as exc:
            if exc.code in (401, 409, 429):
                raise
            # A permanently rejected reply must not poison the entire update queue.
            LOG.warning("Reply rejected for update %s (HTTP %s); continuing", update["update_id"], exc.code)
        except SourceError:
            raise  # Temporary transport failure: retain cursor and retry after reconnecting.
        except Exception as exc:
            LOG.warning("Command failed for update %s (%s)", update["update_id"], type(exc).__name__)
            if getattr(monitor, "config", None) and authorized_command(update, monitor.config.chat_id):
                try:
                    monitor.telegram.message("پردازش این دستور خطا داشت؛ /diagnostics یا /help را امتحان کن.")
                except (SourceError, TelegramError):
                    LOG.warning("Could not deliver the command error notice")
        store.set("telegram_offset", update["update_id"] + 1)


class BackgroundMonitor:
    def __init__(self, config, telegram, *, radar=None, netblocks=netblocks_reports,
                 chart=render_chart, now=lambda: datetime.now(UTC)):
        self.config, self.telegram = config, telegram
        self.radar = radar or RadarClient(config.radar_token)
        self.netblocks, self.chart, self.now = netblocks, chart, now
        self.jobs = queue.Queue(maxsize=2)
        self.pending = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="traffic-monitor", daemon=True)

    def start(self):
        self.thread.start()

    def submit(self, kind):
        if kind not in ("status", "chart") or self.stop.is_set():
            return False
        with self.lock:
            if kind in self.pending:
                return False
            try:
                self.jobs.put_nowait(kind)
            except queue.Full:
                return False
            self.pending.add(kind)
        return True

    def close(self):
        self.stop.set()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        if self.thread.is_alive():
            self.thread.join(timeout=2)

    def _run(self):
        # sqlite connections are owned by the thread that uses them. WAL allows UI reads.
        store = Store(self.config.data_dir / "state.sqlite3")
        monitor = Monitor(self.config, store, self.radar, self.telegram, self.netblocks, self.chart)
        due = 0.0
        try:
            while not self.stop.is_set():
                if time.monotonic() >= due:
                    due = time.monotonic() + self.config.poll_seconds
                    try:
                        monitor.refresh(self.now())
                    except Exception as exc:
                        LOG.warning("Background refresh failed (%s); polling continues", type(exc).__name__)
                if self.stop.is_set():
                    break
                try:
                    kind = self.jobs.get(timeout=max(0.1, due - time.monotonic()))
                except queue.Empty:
                    continue
                if kind is None:
                    break
                try:
                    for attempt in range(3):
                        try:
                            current = self.now()
                            if monitor.needs_refresh(current):
                                monitor.refresh(current, notify=False)
                            result, reports, outages, warnings = monitor.current(self.now())
                            text = report_text(result, self.now(), reports, outages, warnings, **monitor.fetch_times())
                            if kind == "chart":
                                monitor.send_chart(result, text)
                            else:
                                self.telegram.message(text)
                            break
                        except (SourceError, TelegramError) as exc:
                            LOG.warning("Background reply failed (%s), attempt %s", type(exc).__name__, attempt + 1)
                            if isinstance(exc, TelegramError) and exc.code in (400, 401, 403):
                                break
                            if attempt == 2 or self.stop.wait(min(getattr(exc, "retry_after", 5), 60)):
                                break
                        except Exception as exc:
                            LOG.warning("Background command failed (%s)", type(exc).__name__)
                            break
                finally:
                    with self.lock:
                        self.pending.discard(kind)
                    self.jobs.task_done()
        finally:
            store.close()
