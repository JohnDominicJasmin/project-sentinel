import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import Alarm, Event
from .normalize import Rejected, normalize, parse_message
from .store import AlarmStore
from .triage.rules import rule_severity

log = logging.getLogger("sentinel.pipeline")

Listener = Callable[[Alarm], None]


@dataclass
class IngestStats:
    received: int = 0
    accepted: int = 0
    repaired: int = 0
    rejected: int = 0
    duplicates: int = 0


class Pipeline:
    """Single entry point for every event: the stream, the camera worker and the correlator."""

    def __init__(self, store: AlarmStore) -> None:
        self.store = store
        self.stats = IngestStats()
        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def submit(self, raw, origin: str = "stream") -> Optional[Alarm]:
        self.stats.received += 1
        received_at = datetime.now(timezone.utc)
        try:
            event = normalize(parse_message(raw), received_at)
        except Rejected as exc:
            self.stats.rejected += 1
            log.warning("rejected message from %s: %s", origin, exc)
            return None
        except Exception:
            self.stats.rejected += 1
            log.exception("unexpected error normalising message from %s", origin)
            return None
        return self._accept(event)

    def submit_event(self, event: Event) -> Optional[Alarm]:
        self.stats.received += 1
        return self._accept(event)

    def _accept(self, event: Event) -> Optional[Alarm]:
        severity, reason = rule_severity(event)
        alarm = self.store.add(event, severity, reason)
        if alarm is None:
            self.stats.duplicates += 1
            log.info("duplicate %s ignored", event.event_id)
            return None

        self.stats.accepted += 1
        if event.issues:
            self.stats.repaired += 1
            log.info("repaired %s: %s", event.event_id, ", ".join(event.issues))
        for listener in self._listeners:
            listener(alarm)
        return alarm
