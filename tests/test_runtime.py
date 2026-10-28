import tempfile
import json
import threading
import time
import unittest
from pathlib import Path

from iran_monitor.app import Monitor
from iran_monitor.config import Config
from iran_monitor.runtime import BackgroundMonitor, process_updates
from iran_monitor.storage import Store
from iran_monitor.telegram import TelegramClient, TelegramError
from tests.test_analysis import NOW, payload
from tests.test_monitor import FakeTelegram


class RuntimeTests(unittest.TestCase):
    def test_status_replies_while_source_fetch_is_blocked(self):
        entered, release = threading.Event(), threading.Event()
        class SlowRadar:
            def traffic(self, now):
                entered.set()
                release.wait(5)
                return payload((0.8,)*4)
            def outages(self, now):
                return []
        with tempfile.TemporaryDirectory() as tmp:
            config = Config("123:fake", 42, "fake", data_dir=Path(tmp))
            sent = []
            def api(url, **kwargs):
                method = url.rsplit("/", 1)[-1]
                if method == "getUpdates":
                    return {"ok": True, "result": [{"update_id": 11, "message": {
                        "chat": {"id": 42, "type": "private"}, "text": "status"}}]}
                body = json.loads(kwargs["data"])
                sent.append(body["text"])
                self.assertEqual(body["chat_id"], 42)
                return {"ok": True, "result": {"message_id": len(sent)}}
            telegram = TelegramClient("123:fake", 42, request=api)
            worker = BackgroundMonitor(config, telegram, radar=SlowRadar(), netblocks=lambda now: [], now=lambda: NOW)
            store = Store(Path(tmp) / "state.sqlite3")
            try:
                worker.start()
                self.assertTrue(entered.wait(2))
                ui = Monitor(config, store, SlowRadar(), telegram, submit=worker.submit)
                process_updates(ui, store, telegram.updates(0), now=lambda: NOW)
                self.assertTrue(sent, "An immediate reply must precede network completion")
                self.assertEqual(store.get("telegram_offset"), 12)
                self.assertFalse(release.is_set())
                self.assertFalse(worker.submit("status"), "Duplicate work must be coalesced")
                release.set()
                deadline = time.monotonic() + 3
                while len(sent) < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertGreaterEqual(len(sent), 2)
                self.assertIn("روال", sent[-1])
            finally:
                release.set()
                worker.close()
                store.close()

    def test_bad_update_does_not_block_next_status_and_cursor_advances(self):
        class Client(FakeTelegram):
            def message(self, text):
                if text == "bad":
                    raise TelegramError(400)
                super().message(text)
        class Handler:
            def __init__(self, client): self.telegram = client
            def handle(self, update, now): self.telegram.message(update["text"])
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.sqlite3")
            client = Client()
            with self.assertLogs("iran_monitor.runtime", level="WARNING"):
                process_updates(Handler(client), store, [{"update_id": 1, "text": "bad"}, {"update_id": 2, "text": "good"}], now=lambda: NOW)
            self.assertEqual(client.sent, [(None, "good")])
            self.assertEqual(store.get("telegram_offset"), 3)
            store.close()

    def test_rate_limit_keeps_failed_update_pending(self):
        class Handler:
            def handle(self, update, now): raise TelegramError(429, 20)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.sqlite3")
            with self.assertRaises(TelegramError):
                process_updates(Handler(), store, [{"update_id": 3}], now=lambda: NOW)
            self.assertEqual(store.get("telegram_offset", 0), 0)
            store.close()
