import json
import uuid

from fastapi.testclient import TestClient

from app.main import app, pipeline

client = TestClient(app)


def submit(kind="door_forced"):
    event_id = "evt_" + uuid.uuid4().hex[:10]
    pipeline.submit(json.dumps({
        "event_id": event_id, "site_id": "site-101", "zone": "lobby", "type": kind,
        "source": "sensor", "confidence": 0.9, "timestamp": "2026-09-19T12:00:00Z",
    }))
    return event_id


def test_acknowledge_then_resolve():
    event_id = submit()
    r = client.post(f"/api/alarms/{event_id}/acknowledge")
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    r = client.post(f"/api/alarms/{event_id}/resolve")
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_acknowledging_a_resolved_alarm_conflicts():
    event_id = submit()
    client.post(f"/api/alarms/{event_id}/resolve")
    assert client.post(f"/api/alarms/{event_id}/acknowledge").status_code == 409


def test_unknown_alarm_is_404():
    assert client.post("/api/alarms/evt_missing/resolve").status_code == 404


def test_dashboard_socket_sends_snapshot_then_live_changes():
    existing = submit()
    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert existing in {a["event"]["event_id"] for a in snapshot["alarms"]}

        client.post(f"/api/alarms/{existing}/acknowledge")
        delta = ws.receive_json()
        assert delta["type"] == "alarm"
        assert delta["seq"] == snapshot["seq"] + 1
        assert delta["alarm"]["status"] == "acknowledged"
