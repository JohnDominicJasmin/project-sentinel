import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import Event
from app.persistence import AlarmRepository, PersistenceWriter
from app.store import AlarmStore
from app.stream_client import StreamClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "simulator"))
import stream as simulator

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def event(event_id, offset_s=0):
    at = NOW + timedelta(seconds=offset_s)
    return Event(event_id=event_id, site_id="site-101", zone="lobby", type="door_forced", source="sensor",
                 confidence=0.9, timestamp=at, received_at=at)


def test_saved_alarms_come_back_after_a_restart(tmp_path):
    store = AlarmStore()
    repo = AlarmRepository(tmp_path / "a.db")
    writer = PersistenceWriter(repo, store, resume_point=lambda: "evt_b")
    store.add(event("evt_a", 0), "critical", "rule")
    store.add(event("evt_b", 1), "warning", "rule")
    store.acknowledge("evt_a")
    store.resolve("evt_b")
    asyncio.run(writer.flush())
    repo.close()

    reopened = AlarmRepository(tmp_path / "a.db")
    alarms, resume = reopened.load()
    restored = AlarmStore()
    restored.restore(alarms)
    assert resume == "evt_b"
    assert restored.get("evt_a").status == "acknowledged"
    assert restored.get("evt_b").status == "resolved"
    assert restored.seq == store.seq
    assert restored.add(event("evt_a"), "critical", "rule") is None
    assert [a.event.event_id for a in restored.recent()] == ["evt_b", "evt_a"]


def test_writer_saves_only_the_latest_state_once(tmp_path):
    store = AlarmStore()
    repo = AlarmRepository(tmp_path / "b.db")
    writer = PersistenceWriter(repo, store, resume_point=lambda: None)
    store.add(event("evt_a"), "critical", "rule")
    store.acknowledge("evt_a")
    store.resolve("evt_a")
    asyncio.run(writer.flush())
    assert writer.saved == 1
    assert repo.count() == 1
    [alarm], _ = repo.load()
    assert alarm.status == "resolved"


def test_new_numbers_continue_after_restore(tmp_path):
    store = AlarmStore()
    store.restore([store.add(event("evt_a"), "info", "rule")])
    restored = AlarmStore()
    restored.restore(store.recent())
    assert restored.add(event("evt_new", 5), "info", "rule").seq == store.seq + 1


def test_stream_client_asks_to_resume_after_the_last_event():
    client = StreamClient("ws://localhost:8765", pipeline=None)
    assert client.connect_url() == "ws://localhost:8765"
    client.last_event_id = "evt_42"
    assert client.connect_url() == "ws://localhost:8765?since=evt_42"


def test_simulator_replays_only_what_was_missed():
    simulator.history.clear()
    for i in range(5):
        simulator.history.append((f"evt_{i}", f"msg_{i}"))
    assert simulator.missed_since("evt_2") == ["msg_3", "msg_4"]
    assert simulator.missed_since("evt_4") == []
    assert simulator.missed_since("evt_unknown") == [f"msg_{i}" for i in range(5)]
