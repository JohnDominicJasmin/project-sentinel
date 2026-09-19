from datetime import datetime, timezone
from typing import Optional

from .models import Alarm, Event


class AlarmStore:
    def __init__(self) -> None:
        self._alarms: dict[str, Alarm] = {}
        self._seq = 0

    def __len__(self) -> int:
        return len(self._alarms)

    def add(self, event: Event) -> Optional[Alarm]:
        if event.event_id in self._alarms:
            return None
        alarm = Alarm(seq=self._next_seq(), event=event, updated_at=_now())
        self._alarms[event.event_id] = alarm
        return alarm

    def get(self, event_id: str) -> Optional[Alarm]:
        return self._alarms.get(event_id)

    def list(self, limit: int = 100) -> list[Alarm]:
        newest_first = sorted(self._alarms.values(), key=lambda a: a.seq, reverse=True)
        return newest_first[:limit]

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq


def _now() -> datetime:
    return datetime.now(timezone.utc)
