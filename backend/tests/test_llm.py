from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import Event
from app.triage.llm import InvalidOutput, event_payload, parse_results

NOW = datetime(2026, 9, 19, 3, 5, tzinfo=timezone.utc)


def test_parse_valid_output():
    content = '{"results": [{"event_id": "a", "severity": "info", "verdict": "uncertain", "summary": "  Motion   only. ", "action": "Log it."}]}'
    [result] = parse_results(content, 10, 5)
    assert result.summary == "Motion only."


@pytest.mark.parametrize("content", [
    None,
    "not json",
    '{"results": [{"event_id": "a"}]}',
    '{"results": [{"event_id": "a", "severity": "apocalyptic", "verdict": "uncertain", "summary": "x", "action": "y"}]}',
    '{"results": [{"event_id": "a", "severity": "info", "verdict": "uncertain", "summary": "   ", "action": "y"}]}',
    '{"answer": 42}',
])
def test_invalid_output_is_rejected_with_token_counts(content):
    with pytest.raises(InvalidOutput) as info:
        parse_results(content, 10, 5)
    assert info.value.input_tokens == 10 and info.value.output_tokens == 5


def test_payload_uses_site_local_time_and_flags_repairs():
    event = Event(event_id="a", site_id="site-101", zone="lobby", type="motion_detected", source="camera",
                  confidence=None, timestamp=NOW, received_at=NOW, issues=["missing confidence"])
    payload = event_payload(event, ZoneInfo("America/New_York"))
    assert payload["local_time"] == "Fri 23:05"
    assert payload["data_issues"] == ["missing confidence"]
    assert "metadata" not in payload
