import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import Alarm
from .normalize import Rejected, normalize, parse_message
from .store import AlarmStore
from .triage.rules import rule_severity

log = logging.getLogger("sentinel.pipeline")


@dataclass
class IngestStats:
    received: int = 0
    accepted: int = 0
    repaired: int = 0
    rejected: int = 0
    duplicates: int = 0


class Pipeline:
    """Single entry point for every event, from the stream or the camera worker."""

    def __init__(self, store: AlarmStore, on_accepted: Optional[Callable[[Alarm], None]] = None) -> None:
        self.store = store
        self.on_accepted = on_accepted
        self.stats = IngestStats()

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
        if self.on_accepted:
            self.on_accepted(alarm)
        return alarm
