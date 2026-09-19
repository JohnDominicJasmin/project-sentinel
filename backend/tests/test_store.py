from datetime import datetime, timezone

import pytest

from app.models import Event
from app.store import AlarmNotFound, AlarmStore, InvalidTransition

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def event(event_id):
    return Event(
        event_id=event_id, site_id="site-101", zone="lobby", type="door_forced", source="sensor",
        confidence=0.9, timestamp=NOW, received_at=NOW,
    )


def add(store, event_id):
    return store.add(event(event_id), "critical", "test")


def test_every_change_gets_the_next_seq_and_is_announced():
    store = AlarmStore()
    seen = []
    store.subscribe(lambda alarm: seen.append((alarm.seq, alarm.status)))
    add(store, "a")
    store.acknowledge("a")
    store.resolve("a")
    assert seen == [(1, "new"), (2, "acknowledged"), (3, "resolved")]
    assert store.seq == 3


def test_repeated_actions_are_idempotent():
    store = AlarmStore()
    add(store, "a")
    first = store.acknowledge("a")
    assert store.acknowledge("a").seq == first.seq
    resolved = store.resolve("a")
    assert store.resolve("a").seq == resolved.seq


def test_cannot_acknowledge_a_resolved_alarm():
    store = AlarmStore()
    add(store, "a")
    store.resolve("a")
    with pytest.raises(InvalidTransition):
        store.acknowledge("a")


def test_resolving_directly_also_stamps_acknowledged():
    store = AlarmStore()
    add(store, "a")
    alarm = store.resolve("a")
    assert alarm.acknowledged_at is not None


def test_unknown_alarm():
    with pytest.raises(AlarmNotFound):
        AlarmStore().resolve("nope")


def test_oldest_resolved_alarms_are_evicted_but_open_ones_stay():
    store = AlarmStore(max_resolved=2)
    for i in range(5):
        add(store, f"r{i}")
        store.resolve(f"r{i}")
    add(store, "open")
    assert store.get("r0") is None and store.get("r2") is None
    assert store.get("r3") and store.get("r4") and store.get("open")
    assert len(store) == 3


def test_evicted_alarm_is_still_deduplicated():
    store = AlarmStore(max_resolved=1)
    add(store, "a")
    store.resolve("a")
    add(store, "b")
    store.resolve("b")
    assert store.get("a") is None
    assert add(store, "a") is None


def test_dedupe_memory_is_bounded():
    store = AlarmStore(max_seen=3)
    for i in range(5):
        add(store, f"e{i}")
    assert len(store._seen) == 3


def test_snapshot_has_all_open_and_recent_resolved():
    store = AlarmStore()
    for i in range(4):
        add(store, f"e{i}")
    store.resolve("e0")
    store.resolve("e1")
    ids = {a.event.event_id for a in store.snapshot(resolved_limit=1)}
    assert ids == {"e2", "e3", "e1"}
