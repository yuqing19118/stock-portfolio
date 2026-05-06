"""
AgentMemory — SQLite-backed long-term memory for the research agent.

Schema
  memories(id, at, type, payload_json)

The dashboard summary JSON is still written after each write so index.html
can load it without touching the database directly.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_FILE = Path("data/agent_memory.db")
MEMORY_SUMMARY_FILE = Path("data/memory_summary.json")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT    NOT NULL,
    type         TEXT    NOT NULL,
    payload_json TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_at   ON memories(at);
"""


class AgentMemory:
    def __init__(self, path: Path = DB_FILE):
        self.path = path
        self.path.parent.mkdir(exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def remember(self, memory_type: str, payload: dict):
        at = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO memories (at, type, payload_json) VALUES (?, ?, ?)",
                (at, memory_type, json.dumps(payload, ensure_ascii=False)),
            )
        self.write_summary()

    def recent(self, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT at, type, payload_json FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"at": r["at"], "type": r["type"], "payload": json.loads(r["payload_json"])}
            for r in reversed(rows)
        ]

    def by_type(self, memory_type: str, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT at, type, payload_json FROM memories WHERE type = ? ORDER BY id DESC LIMIT ?",
                (memory_type, limit),
            ).fetchall()
        return [
            {"at": r["at"], "type": r["type"], "payload": json.loads(r["payload_json"])}
            for r in reversed(rows)
        ]

    def count_by_type(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT type, COUNT(*) as n FROM memories GROUP BY type"
            ).fetchall()
        return {r["type"]: r["n"] for r in rows}

    def latest_by_type(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT type, MAX(at) as latest FROM memories GROUP BY type"
            ).fetchall()
        return {r["type"]: r["latest"] for r in rows}

    def write_summary(self) -> dict:
        recent = self.recent(12)
        summary = {
            "updated_at": datetime.now().isoformat(),
            "db_file": str(self.path),
            "counts_by_type": self.count_by_type(),
            "latest_by_type": self.latest_by_type(),
            "recent_entries": recent,
        }
        MEMORY_SUMMARY_FILE.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False)
        )
        return summary
