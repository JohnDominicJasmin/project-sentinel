from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

EVENT_TYPES = {
    "motion_detected", "perimeter_breach", "door_forced", "glass_break",
    "smoke_detected", "fire_alarm", "object_detected", "loitering",
    "camera_offline", "sensor_fault", "panic_button",
}
CAMERA_TYPES = {"motion_detected", "object_detected", "loitering", "glass_break"}

Severity = Literal["info", "warning", "critical"]
Status = Literal["new", "acknowledged", "resolved"]
Verdict = Literal["likely_real", "probable_false_positive", "uncertain"]
TriageStatus = Literal["pending", "ai", "rules"]

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


class Event(BaseModel):
    event_id: str
    site_id: str
    zone: str
    type: str
    source: Literal["camera", "sensor"]
    confidence: Optional[float]
    timestamp: datetime
    snapshot_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    received_at: datetime
    issues: list[str] = Field(default_factory=list)


class AiTriage(BaseModel):
    severity: Severity
    verdict: Verdict
    summary: str
    action: str
    model: str
    latency_ms: int


class Alarm(BaseModel):
    seq: int
    event: Event
    status: Status = "new"
    severity: Severity
    severity_source: Literal["rules", "ai"] = "rules"
    reason: str
    triage_status: TriageStatus = "pending"
    triage_note: Optional[str] = None
    ai: Optional[AiTriage] = None
    updated_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
