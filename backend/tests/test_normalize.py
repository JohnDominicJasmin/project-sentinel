from datetime import datetime, timezone

import pytest

from app.normalize import Rejected, normalize, parse_message

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def event(**overrides):
    base = {
        "event_id": "evt_1",
        "site_id": "site-101",
        "zone": "lobby",
        "type": "door_forced",
        "source": "sensor",
        "confidence": 0.8,
        "timestamp": "2026-09-19T11:59:58Z",
        "snapshot_url": None,
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_clean_event_has_no_issues():
    e = normalize(event(), NOW)
    assert e.issues == []
    assert e.confidence == 0.8
    assert e.timestamp == datetime(2026, 9, 19, 11, 59, 58, tzinfo=timezone.utc)


def test_missing_fields_are_repaired_and_flagged():
    data = event()
    for key in ("site_id", "zone", "source"):
        data.pop(key)
    e = normalize(data, NOW)
    assert e.site_id == "unknown-site"
    assert e.zone == "unknown-zone"
    assert e.source == "sensor"
    assert {"missing site_id", "missing zone", "missing source"} <= set(e.issues)


def test_source_is_inferred_from_camera_type():
    data = event(type="loitering")
    data.pop("source")
    assert normalize(data, NOW).source == "camera"


@pytest.mark.parametrize("bad", ["high", 1.7, -0.2, None, True, float("nan")])
def test_bad_confidence_becomes_none(bad):
    e = normalize(event(confidence=bad), NOW)
    assert e.confidence is None
    assert "invalid confidence" in e.issues


def test_unknown_type_is_kept_for_triage():
    e = normalize(event(type="alien_invasion"), NOW)
    assert e.type == "alien_invasion"
    assert "unrecognised type 'alien_invasion'" in e.issues


def test_bad_timestamp_falls_back_to_received_time():
    e = normalize(event(timestamp="yesterday-ish"), NOW)
    assert e.timestamp == NOW
    assert "invalid timestamp" in e.issues


def test_missing_event_id_gets_generated():
    data = event()
    data.pop("event_id")
    e = normalize(data, NOW)
    assert e.event_id.startswith("gen_")
    assert "missing event_id" in e.issues


@pytest.mark.parametrize("raw", ['{"event_id": "evt_broken", "type": ', "", b"\xff", 42])
def test_unparseable_messages_are_rejected(raw):
    with pytest.raises(Rejected):
        parse_message(raw)


@pytest.mark.parametrize("raw", ["[]", "null", '"text"'])
def test_non_object_json_is_rejected(raw):
    with pytest.raises(Rejected):
        parse_message(raw)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,x", 42, "//evil.example/x.jpg", r"/\evil.example/x.jpg",
    "/api/chaos/429", "/snapshots/../api/health",
])
def test_unsafe_snapshot_urls_are_dropped(url):
    e = normalize(event(snapshot_url=url), NOW)
    assert e.snapshot_url is None
    assert "invalid snapshot_url" in e.issues


def test_safe_snapshot_urls_are_kept():
    assert normalize(event(snapshot_url="/snapshots/cam_1.jpg"), NOW).snapshot_url == "/snapshots/cam_1.jpg"
