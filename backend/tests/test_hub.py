import json
from datetime import datetime, timezone

from app.hub import RESYNC, DashboardHub
from app.models import Event
from app.store import AlarmStore

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def add(store, event_id):
    store.add(
        Event(event_id=event_id, site_id="s", zone="z", type="fire_alarm", source="sensor",
              confidence=0.9, timestamp=NOW, received_at=NOW),
        "critical", "test",
    )


def test_snapshot_then_ordered_deltas():
    store = AlarmStore()
    hub = DashboardHub(store)
    add(store, "before")
    queue, snapshot = hub.connect()
    snap = json.loads(snapshot)
    assert snap["seq"] == 1 and [a["event"]["event_id"] for a in snap["alarms"]] == ["before"]

    add(store, "after")
    store.acknowledge("after")
    deltas = [json.loads(queue.get_nowait()) for _ in range(2)]
    assert [d["seq"] for d in deltas] == [2, 3]
    assert deltas[1]["alarm"]["status"] == "acknowledged"


def test_slow_dashboard_gets_a_resync_instead_of_blocking():
    store = AlarmStore()
    hub = DashboardHub(store, queue_size=3)
    queue, _ = hub.connect()
    for i in range(10):
        add(store, f"e{i}")
    assert hub.resyncs >= 1
    items = [queue.get_nowait() for _ in range(queue.qsize())]
    assert RESYNC in items


def test_disconnected_dashboard_stops_receiving():
    store = AlarmStore()
    hub = DashboardHub(store)
    queue, _ = hub.connect()
    hub.disconnect(queue)
    add(store, "e")
    assert queue.empty()
