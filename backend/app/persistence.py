import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

from .models import Alarm
from .store import AlarmStore

log = logging.getLogger("sentinel.persistence")

SCHEMA = """
CREATE TABLE IF NOT EXISTS alarms (
    event_id    TEXT PRIMARY KEY,
    seq         INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    status      TEXT NOT NULL,
    resolved_at TEXT,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS alarms_status ON alarms(status, resolved_at);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

UPSERT = """
INSERT INTO alarms (event_id, seq, received_at, status, resolved_at, data)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(event_id) DO UPDATE SET
    seq = excluded.seq, status = excluded.status, resolved_at = excluded.resolved_at, data = excluded.data
"""


class AlarmRepository:
    """SQLite storage for alarms and the stream resume point."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)

    def load(self, resolved_limit: int = 5000) -> tuple[list[Alarm], Optional[str]]:
        open_rows = self._conn.execute("SELECT data FROM alarms WHERE status != 'resolved'").fetchall()
        resolved_rows = self._conn.execute(
            "SELECT data FROM alarms WHERE status = 'resolved' ORDER BY resolved_at DESC LIMIT ?", (resolved_limit,)
        ).fetchall()
        alarms = [Alarm.model_validate_json(row[0]) for row in open_rows + resolved_rows]
        return alarms, self.get_meta("last_stream_event_id")

    def save(self, alarms: list[Alarm], last_stream_event_id: Optional[str]) -> None:
        rows = [
            (
                a.event.event_id,
                a.seq,
                a.event.received_at.isoformat(),
                a.status,
                a.resolved_at.isoformat() if a.resolved_at else None,
                a.model_dump_json(),
            )
            for a in alarms
        ]
        with self._conn:
            self._conn.executemany(UPSERT, rows)
            if last_stream_event_id:
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('last_stream_event_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (last_stream_event_id,),
                )

    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM alarms").fetchone()[0]

    def close(self) -> None:
        self._conn.close()


class PersistenceWriter:
    """Write-behind: collects store changes and saves them in one transaction every interval.

    Writes happen in a worker thread, so disk latency never blocks the event loop.
    Several changes to the same alarm between flushes are saved once, in their latest state.
    """

    def __init__(
        self,
        repo: AlarmRepository,
        store: AlarmStore,
        resume_point: Callable[[], Optional[str]],
        interval_s: float = 0.25,
    ) -> None:
        self.repo = repo
        self.resume_point = resume_point
        self.interval_s = interval_s
        self.restored = 0
        self.saved = 0
        self.last_flush_ms: Optional[float] = None
        self._dirty: dict[str, Alarm] = {}
        self._saved_resume_point: Optional[str] = None
        store.subscribe(self._on_change)

    def stats(self) -> dict:
        return {
            "db": self.repo.path.name,
            "restored": self.restored,
            "saved": self.saved,
            "pending_writes": len(self._dirty),
            "last_flush_ms": self.last_flush_ms,
        }

    def _on_change(self, alarm: Alarm) -> None:
        self._dirty[alarm.event.event_id] = alarm

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            try:
                await self.flush()
            except Exception:
                log.exception("saving alarms failed, will retry")

    async def flush(self) -> None:
        resume_point = self.resume_point()
        if not self._dirty and resume_point == self._saved_resume_point:
            return
        batch = list(self._dirty.values())
        self._dirty = {}
        started = time.monotonic()
        try:
            await asyncio.to_thread(self.repo.save, batch, resume_point)
        except Exception:
            for alarm in batch:
                self._dirty.setdefault(alarm.event.event_id, alarm)
            raise
        self.saved += len(batch)
        self._saved_resume_point = resume_point
        self.last_flush_ms = round((time.monotonic() - started) * 1000, 1)
