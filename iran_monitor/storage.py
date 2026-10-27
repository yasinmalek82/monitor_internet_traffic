"""Small SQLite state store: restarts preserve incident and Telegram cursor state."""

import json
import sqlite3
from pathlib import Path

from .analysis import Assessment


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.commit()

    def get(self, key, default=None):
        row = self.connection.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connection:
            self.connection.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                    (key, json.dumps(value, ensure_ascii=False)))

    def close(self):
        self.connection.close()


def alert_kind(result: Assessment, active: str) -> str | None:
    if result.status == "unknown":
        return None
    if result.recovery_ready and active != "none":
        return "recovery"
    ranks = {"none": 0, "severe": 1, "critical": 2}
    if result.status in ranks and ranks[result.status] > ranks[active]:
        return result.status
    return None
