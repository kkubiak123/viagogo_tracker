#!/usr/bin/env python3
import sqlite3
from typing import Dict, List, Optional

DB_FILE = "prices.db"

_DDL = """
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    floor_price REAL NOT NULL,
    currency TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ep ON prices(event_id, platform);
CREATE INDEX IF NOT EXISTS idx_ts ON prices(timestamp);
"""

class Database:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self._conn = None

    def __enter__(self):
        self._conn = sqlite3.connect(self.db_file)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()
        return self

    def __exit__(self, *args):
        if self._conn:
            self._conn.close()

    def save(self, timestamp, event_id, event_name, platform, floor_price, currency):
        try:
            self._conn.execute(
                "INSERT INTO prices (timestamp,event_id,event_name,platform,floor_price,currency) VALUES (?,?,?,?,?,?)",
                (timestamp, event_id, event_name, platform, floor_price, currency),
            )
            self._conn.commit()
            return True
        except sqlite3.Error:
            return False

    def get_event_history(self, event_id, platform=None, limit=200):
        if platform:
            return self._conn.execute(
                "SELECT * FROM prices WHERE event_id=? AND platform=? ORDER BY timestamp DESC LIMIT ?",
                (event_id, platform, limit),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM prices WHERE event_id=? ORDER BY timestamp DESC LIMIT ?",
            (event_id, limit),
        ).fetchall()

    def get_latest_per_platform(self, event_id):
        rows = self._conn.execute(
            "SELECT * FROM prices WHERE id IN (SELECT MAX(id) FROM prices WHERE event_id=? GROUP BY platform)",
            (event_id,),
        ).fetchall()
        return {row["platform"]: row for row in rows}

    def get_all_events_latest(self):
        return self._conn.execute(
            "SELECT * FROM prices WHERE id IN (SELECT MAX(id) FROM prices GROUP BY event_id, platform) ORDER BY event_id, platform"
        ).fetchall()
