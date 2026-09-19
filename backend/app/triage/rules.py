from ..models import Event, Severity

LIFE_SAFETY = {"panic_button", "fire_alarm", "smoke_detected"}
ALWAYS_CRITICAL = LIFE_SAFETY | {"escalation"}
INTRUSION = {"perimeter_breach", "door_forced", "glass_break"}
EQUIPMENT = {"camera_offline", "sensor_fault"}

HIGH_CONFIDENCE = 0.8
PERSON_CONFIDENCE = 0.6


def rule_severity(event: Event) -> tuple[Severity, str]:
    kind, confidence = event.type, event.confidence

    if kind == "escalation":
        return "critical", event.metadata.get("summary") or "Escalated incident."

    if kind in LIFE_SAFETY:
        return "critical", "Life-safety alarm. Treat as real until verified."

    if kind in INTRUSION:
        if confidence is not None and confidence >= HIGH_CONFIDENCE:
            return "critical", f"High-confidence intrusion ({confidence:.0%})."
        return "warning", f"Possible intrusion, confidence {_pct(confidence)}."

    if kind in EQUIPMENT:
        return "warning", "Equipment problem. Coverage at this zone may be down."

    if kind == "loitering":
        return "warning", "Someone lingering in a monitored zone."

    if kind == "object_detected":
        obj = event.metadata.get("object") or "object"
        if obj == "person" and confidence is not None and confidence >= PERSON_CONFIDENCE:
            return "warning", f"Person detected ({confidence:.0%})."
        return "info", f"{str(obj).capitalize()} detected, confidence {_pct(confidence)}."

    if kind == "motion_detected":
        return "info", "Motion only. A common false-alarm source."

    return "warning", f"Unrecognised alarm type '{kind}'. Needs a human look."


def _pct(confidence) -> str:
    return "unknown" if confidence is None else f"{confidence:.0%}"
