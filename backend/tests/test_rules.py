from datetime import datetime, timezone

import pytest

from app.models import Event
from app.triage.rules import rule_severity

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def event(kind, confidence=0.5, **metadata):
    return Event(
        event_id="evt_1", site_id="site-101", zone="lobby", type=kind, source="sensor",
        confidence=confidence, timestamp=NOW, received_at=NOW, metadata=metadata,
    )


@pytest.mark.parametrize("kind", ["panic_button", "fire_alarm", "smoke_detected"])
def test_life_safety_is_always_critical(kind):
    assert rule_severity(event(kind, confidence=0.1))[0] == "critical"
    assert rule_severity(event(kind, confidence=None))[0] == "critical"


def test_intrusion_depends_on_confidence():
    assert rule_severity(event("door_forced", 0.92))[0] == "critical"
    assert rule_severity(event("door_forced", 0.55))[0] == "warning"
    assert rule_severity(event("door_forced", None))[0] == "warning"


def test_person_vs_animal():
    assert rule_severity(event("object_detected", 0.8, object="person"))[0] == "warning"
    assert rule_severity(event("object_detected", 0.8, object="animal"))[0] == "info"


def test_motion_is_info():
    assert rule_severity(event("motion_detected", 0.99))[0] == "info"


def test_unknown_type_gets_a_human_look():
    severity, reason = rule_severity(event("alien_invasion"))
    assert severity == "warning"
    assert "alien_invasion" in reason
