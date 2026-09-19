import json

from app.pipeline import Pipeline
from app.store import AlarmStore


def message(event_id="evt_1", **extra):
    return json.dumps({
        "event_id": event_id,
        "site_id": "site-101",
        "zone": "lobby",
        "type": "glass_break",
        "source": "camera",
        "confidence": 0.9,
        "timestamp": "2026-09-19T12:00:00Z",
        **extra,
    })


def test_duplicate_is_counted_not_stored_twice():
    pipeline = Pipeline(AlarmStore())
    assert pipeline.submit(message()) is not None
    assert pipeline.submit(message()) is None
    assert len(pipeline.store) == 1
    assert pipeline.stats.duplicates == 1


def test_junk_never_raises_and_is_accounted_for():
    pipeline = Pipeline(AlarmStore())
    junk = ["", "null", "[]", "{", b"\xff", 42, '{"confidence": {}, "type": 5, "metadata": "x"}']
    for raw in junk:
        pipeline.submit(raw)
    s = pipeline.stats
    assert s.received == len(junk)
    assert s.received == s.accepted + s.rejected + s.duplicates
    assert s.accepted == 1 and s.repaired == 1


def test_alarms_list_newest_first():
    pipeline = Pipeline(AlarmStore())
    for i in range(3):
        pipeline.submit(message(event_id=f"evt_{i}"))
    ids = [a.event.event_id for a in pipeline.store.recent()]
    assert ids == ["evt_2", "evt_1", "evt_0"]
