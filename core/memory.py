"""
AgentMemory — append-only long-term memory for the research agent.

The dashboard stays curated, but this file keeps the full trail of what the
agent saw, learned, and decided over time.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path("data/agent_memory.jsonl")
MEMORY_SUMMARY_FILE = Path("data/memory_summary.json")


class AgentMemory:
    def __init__(self, path: Path = MEMORY_FILE):
        self.path = path
        self.path.parent.mkdir(exist_ok=True)

    def remember(self, memory_type: str, payload: dict):
        entry = {
            "at": datetime.now().isoformat(),
            "type": memory_type,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.write_summary()

    def recent(self, limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries

    def write_summary(self) -> dict:
        entries = self.recent(5000)
        counts = {}
        latest = {}
        for entry in entries:
            kind = entry.get("type", "unknown")
            counts[kind] = counts.get(kind, 0) + 1
            latest[kind] = entry.get("at")

        summary = {
            "updated_at": datetime.now().isoformat(),
            "memory_file": str(self.path),
            "total_recent_entries_counted": len(entries),
            "counts_by_type": counts,
            "latest_by_type": latest,
            "recent_entries": entries[-12:],
        }
        MEMORY_SUMMARY_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary
