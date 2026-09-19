from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import Alarm, Event, Severity

Listener = Callable[[Alarm], None]


class AlarmNotFound(KeyError):
    pass


class InvalidTransition(Exception):
    pass


class AlarmStore:
    """In-memory alarm state. Every change gets the next sequence number and is announced to listeners."""

    def __init__(self, max_resolved: int = 5000, max_seen: int = 100_000) -> None:
        self._alarms: dict[str, Alarm] = {}
        self._seen: dict[str, None] = {}
        self._resolved: deque[str] = deque()
        self._listeners: list[Listener] = []
        self._seq = 0
        self.max_resolved = max_resolved
        self.max_seen = max_seen

    def __len__(self) -> int:
        return len(self._alarms)

    @property
    def seq(self) -> int:
        return self._seq

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def add(self, event: Event, severity: Severity, reason: str) -> Optional[Alarm]:
        if event.event_id in self._seen:
            return None
        self._remember(event.event_id)
        alarm = Alarm(
            seq=self._next_seq(), event=event, severity=severity, reason=reason, updated_at=_now()
        )
        self._alarms[event.event_id] = alarm
        self._emit(alarm)
        return alarm

    def acknowledge(self, event_id: str) -> Alarm:
        alarm = self._require(event_id)
        if alarm.status == "resolved":
            raise InvalidTransition("alarm is already resolved")
        if alarm.status == "acknowledged":
            return alarm
        return self._update(alarm, status="acknowledged", acknowledged_at=_now())

    def resolve(self, event_id: str) -> Alarm:
        alarm = self._require(event_id)
        if alarm.status == "resolved":
            return alarm
        now = _now()
        updated = self._update(
            alarm, status="resolved", resolved_at=now, acknowledged_at=alarm.acknowledged_at or now
        )
        self._resolved.append(event_id)
        while len(self._resolved) > self.max_resolved:
            self._alarms.pop(self._resolved.popleft(), None)
        return updated

    def get(self, event_id: str) -> Optional[Alarm]:
        return self._alarms.get(event_id)

    def recent(self, limit: int = 100) -> list[Alarm]:
        return list(reversed(self._alarms.values()))[:limit]

    def snapshot(self, resolved_limit: int = 200) -> list[Alarm]:
        active = [a for a in self._alarms.values() if a.status != "resolved"]
        recent = list(self._resolved)[-resolved_limit:]
        return active + [self._alarms[i] for i in recent if i in self._alarms]

    def _update(self, alarm: Alarm, **changes) -> Alarm:
        updated = alarm.model_copy(update={**changes, "seq": self._next_seq(), "updated_at": _now()})
        self._alarms[alarm.event.event_id] = updated
        self._emit(updated)
        return updated

    def _require(self, event_id: str) -> Alarm:
        alarm = self._alarms.get(event_id)
        if alarm is None:
            raise AlarmNotFound(event_id)
        return alarm

    def _remember(self, event_id: str) -> None:
        self._seen[event_id] = None
        if len(self._seen) > self.max_seen:
            del self._seen[next(iter(self._seen))]

    def _emit(self, alarm: Alarm) -> None:
        for listener in self._listeners:
            listener(alarm)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq


def _now() -> datetime:
    return datetime.now(timezone.utc)
