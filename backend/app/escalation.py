import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import Alarm, Event
from .pipeline import Pipeline
from .store import AlarmStore
from .triage.rules import INTRUSION

log = logging.getLogger("sentinel.escalation")

MIN_INTRUSION_CONFIDENCE = 0.7
MIN_PERSON_CONFIDENCE = 0.5

RULE_TITLES = {
    "repeated_intrusion": "Repeated intrusion",
    "camera_corroborated": "Intrusion corroborated by camera",
}


@dataclass
class Signal:
    at: float
    event_id: str
    type: str
    zone: str
    source: str
    obj: Optional[str]


class Correlator:

    def __init__(
        self,
        pipeline: Pipeline,
        store: AlarmStore,
        window_s: float = 120.0,
        repeat_threshold: int = 3,
        idle_s: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pipeline = pipeline
        self.store = store
        self.window_s = window_s
        self.repeat_threshold = repeat_threshold
        self.idle_s = idle_s
        self.clock = clock
        self.recent: dict[str, deque[Signal]] = defaultdict(deque)
        self.open: dict[tuple[str, str], list] = {}
        self.consumed: set[str] = set()
        self.incidents_opened = 0

    def stats(self) -> dict:
        return {
            "incidents_opened": self.incidents_opened,
            "window_s": self.window_s,
            "repeat_threshold": self.repeat_threshold,
        }

    def observe(self, alarm: Alarm) -> None:
        event = alarm.event
        if not self._relevant(event):
            return
        now = self.clock()
        signals = self.recent[event.site_id]
        signals.append(Signal(now, event.event_id, event.type, event.zone, event.source, event.metadata.get("object")))
        while signals and now - signals[0].at > self.window_s:
            self.consumed.discard(signals.popleft().event_id)

        intrusions = [s for s in signals if s.type in INTRUSION]
        if len(intrusions) >= self.repeat_threshold:
            self._escalate(event.site_id, "repeated_intrusion", intrusions, now)

        for zone in {s.zone for s in signals}:
            people = [s for s in signals if s.zone == zone and s.source == "camera" and s.obj == "person"]
            sensors = [s for s in signals if s.zone == zone and s.source == "sensor" and s.type in INTRUSION]
            if people and sensors:
                self._escalate(event.site_id, "camera_corroborated", people + sensors, now)

    @staticmethod
    def _relevant(event: Event) -> bool:
        if event.type == "escalation":
            return False
        if event.type in INTRUSION:
            return event.confidence is not None and event.confidence >= MIN_INTRUSION_CONFIDENCE
        is_person = event.source == "camera" and event.metadata.get("object") == "person"
        return is_person and event.confidence is not None and event.confidence >= MIN_PERSON_CONFIDENCE

    def _escalate(self, site_id: str, rule: str, signals: list[Signal], now: float) -> None:
        key = (site_id, rule)
        existing = self.open.get(key)
        if existing:
            incident = self.store.get(existing[0])
            if incident and incident.status != "resolved" and now - existing[1] <= self.idle_s:
                self._attach(incident, signals)
                existing[1] = now
                return

        signals = [s for s in signals if s.event_id not in self.consumed]
        if rule == "repeated_intrusion" and len(signals) < self.repeat_threshold:
            return
        if rule == "camera_corroborated" and not (
            any(s.source == "camera" for s in signals) and any(s.source == "sensor" for s in signals)
        ):
            return

        event = self._incident_event(site_id, rule, signals)
        alarm = self.pipeline.submit_event(event)
        if alarm is None:
            return
        self.open[key] = [event.event_id, now]
        self.incidents_opened += 1
        for signal in signals:
            self.consumed.add(signal.event_id)
            self.store.update(signal.event_id, incident_id=event.event_id)
        log.warning("escalated %s at %s: %s", rule, site_id, event.metadata["summary"])

    def _attach(self, incident: Alarm, signals: list[Signal]) -> None:
        known = set(incident.event.metadata["alarm_ids"])
        new = [s for s in signals if s.event_id not in known]
        if not new:
            return
        linked = [*self._linked(incident), *new]
        metadata = self._metadata(incident.event.metadata["rule"], incident.event.site_id, linked)
        event = incident.event.model_copy(update={"metadata": metadata, "zone": _zone(linked)})
        self.store.update(incident.event.event_id, event=event, reason=metadata["summary"])
        for signal in new:
            self.consumed.add(signal.event_id)
            self.store.update(signal.event_id, incident_id=incident.event.event_id)

    def _linked(self, incident: Alarm) -> list[Signal]:
        signals = []
        for alarm_id in incident.event.metadata["alarm_ids"]:
            alarm = self.store.get(alarm_id)
            if alarm:
                e = alarm.event
                signals.append(Signal(0, e.event_id, e.type, e.zone, e.source, e.metadata.get("object")))
        return signals

    def _incident_event(self, site_id: str, rule: str, signals: list[Signal]) -> Event:
        now = datetime.now(timezone.utc)
        return Event(
            event_id="esc_" + uuid.uuid4().hex[:10],
            site_id=site_id,
            zone=_zone(signals),
            type="escalation",
            source="system",
            confidence=None,
            timestamp=now,
            received_at=now,
            metadata=self._metadata(rule, site_id, signals),
        )

    def _metadata(self, rule: str, site_id: str, signals: list[Signal]) -> dict:
        kinds = sorted({s.type.replace("_", " ") for s in signals})
        if rule == "camera_corroborated":
            summary = f"Camera saw a person while intrusion sensors fired at {site_id} ({', '.join(kinds)})."
        else:
            minutes = round(self.window_s / 60)
            summary = f"{len(signals)} intrusion alarms at {site_id} within {minutes} min ({', '.join(kinds)})."
        return {
            "rule": rule,
            "title": RULE_TITLES[rule],
            "summary": summary,
            "alarm_ids": [s.event_id for s in signals],
            "alarm_types": kinds,
            "zones": sorted({s.zone for s in signals}),
            "count": len(signals),
        }


def _zone(signals: list[Signal]) -> str:
    zones = {s.zone for s in signals}
    return zones.pop() if len(zones) == 1 else "multiple zones"
