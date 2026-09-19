import uuid

from app.escalation import Correlator
from app.pipeline import Pipeline
from app.store import AlarmStore


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def setup(**kwargs):
    store = AlarmStore()
    pipeline = Pipeline(store)
    clock = Clock()
    correlator = Correlator(pipeline, store, clock=clock, **kwargs)
    pipeline.add_listener(correlator.observe)
    return store, pipeline, correlator, clock


def send(pipeline, kind="door_forced", site="site-101", zone="lobby", source="sensor", confidence=0.9, **metadata):
    alarm = pipeline.submit({
        "event_id": "evt_" + uuid.uuid4().hex[:8], "site_id": site, "zone": zone, "type": kind,
        "source": source, "confidence": confidence, "timestamp": "2026-09-19T12:00:00Z", "metadata": metadata,
    })
    return alarm.event.event_id


def incidents(store):
    return [a for a in store.recent(1000) if a.event.type == "escalation"]


def test_three_intrusions_at_one_site_open_one_critical_incident():
    store, pipeline, _, clock = setup()
    ids = []
    for kind in ("door_forced", "perimeter_breach", "glass_break"):
        ids.append(send(pipeline, kind))
        clock.now += 10
    [incident] = incidents(store)
    assert incident.severity == "critical"
    assert incident.event.metadata["rule"] == "repeated_intrusion"
    assert incident.event.metadata["alarm_ids"] == ids
    assert all(store.get(i).incident_id == incident.event.event_id for i in ids)


def test_intrusions_spread_across_sites_do_not_escalate():
    store, pipeline, _, _ = setup()
    for site in ("site-101", "site-102", "site-103"):
        send(pipeline, site=site)
    assert incidents(store) == []


def test_intrusions_outside_the_window_do_not_escalate():
    store, pipeline, _, clock = setup(window_s=60)
    for _ in range(3):
        send(pipeline)
        clock.now += 45
    assert incidents(store) == []


def test_low_confidence_intrusions_are_ignored():
    store, pipeline, _, _ = setup()
    for _ in range(5):
        send(pipeline, confidence=0.4)
    assert incidents(store) == []


def test_later_alarms_join_the_open_incident():
    store, pipeline, _, clock = setup()
    for _ in range(3):
        send(pipeline)
        clock.now += 5
    fourth = send(pipeline)
    [incident] = incidents(store)
    assert incident.event.metadata["count"] == 4
    assert store.get(fourth).incident_id == incident.event.event_id


def test_a_resolved_incident_is_not_reopened_by_the_same_alarms():
    store, pipeline, _, clock = setup()
    for _ in range(3):
        send(pipeline)
        clock.now += 5
    [incident] = incidents(store)
    store.resolve(incident.event.event_id)
    send(pipeline)
    assert len(incidents(store)) == 1


def test_camera_person_plus_sensor_in_the_same_zone_is_corroborated():
    store, pipeline, _, _ = setup()
    send(pipeline, kind="object_detected", source="camera", zone="loading-dock", confidence=0.7, object="person")
    send(pipeline, kind="door_forced", zone="loading-dock")
    [incident] = incidents(store)
    assert incident.event.metadata["rule"] == "camera_corroborated"


def test_camera_and_sensor_in_different_zones_are_not_corroborated():
    store, pipeline, _, _ = setup()
    send(pipeline, kind="object_detected", source="camera", zone="loading-dock", confidence=0.7, object="person")
    send(pipeline, kind="door_forced", zone="roof")
    assert incidents(store) == []


def test_resolving_an_incident_resolves_its_alarms():
    store, pipeline, _, clock = setup()
    ids = []
    for _ in range(3):
        ids.append(send(pipeline))
        clock.now += 5
    [incident] = incidents(store)
    store.acknowledge(incident.event.event_id)
    assert all(store.get(i).status == "acknowledged" for i in ids)
    store.resolve(incident.event.event_id)
    assert all(store.get(i).status == "resolved" for i in ids)


def test_feed_cannot_inject_an_escalation():
    store, pipeline, _, _ = setup()
    alarm = pipeline.submit({
        "event_id": "evt_fake", "site_id": "site-101", "zone": "lobby", "type": "escalation",
        "source": "system", "confidence": 0.9, "timestamp": "2026-09-19T12:00:00Z",
    })
    assert alarm.event.source == "sensor"
    assert "invalid source" in alarm.event.issues
