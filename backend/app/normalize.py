import json
import uuid
from datetime import datetime, timezone

from .models import CAMERA_TYPES, EVENT_TYPES, Event


class Rejected(Exception):
    pass


def parse_message(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise Rejected("not valid JSON") from exc
    if not isinstance(data, dict):
        raise Rejected("JSON is not an object")
    return data


def normalize(data: dict, received_at: datetime) -> Event:
    issues: list[str] = []

    def problem(key: str) -> str:
        return f"{'invalid' if key in data else 'missing'} {key}"

    def text(key: str, fallback):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        issues.append(problem(key))
        return fallback

    event_id = text("event_id", None) or "gen_" + uuid.uuid4().hex[:10]
    site_id = text("site_id", "unknown-site")
    zone = text("zone", "unknown-zone")
    event_type = text("type", "unknown")
    if event_type != "unknown" and event_type not in EVENT_TYPES:
        issues.append(f"unrecognised type '{event_type}'")

    source = data.get("source")
    if source not in ("camera", "sensor"):
        issues.append(problem("source"))
        source = "camera" if event_type in CAMERA_TYPES else "sensor"

    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
            or not 0 <= confidence <= 1:
        issues.append(problem("confidence"))
        confidence = None

    timestamp = _parse_time(data.get("timestamp"))
    if timestamp is None:
        issues.append(problem("timestamp"))
        timestamp = received_at

    snapshot_url = data.get("snapshot_url")
    if snapshot_url is not None and not (
        isinstance(snapshot_url, str) and snapshot_url.startswith(("https://", "http://", "/"))
    ):
        issues.append(problem("snapshot_url"))
        snapshot_url = None

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        if metadata is not None:
            issues.append(problem("metadata"))
        metadata = {}

    return Event(
        event_id=event_id,
        site_id=site_id,
        zone=zone,
        type=event_type,
        source=source,
        confidence=confidence,
        timestamp=timestamp,
        snapshot_url=snapshot_url,
        metadata=metadata,
        received_at=received_at,
        issues=issues,
    )


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
