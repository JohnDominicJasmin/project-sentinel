import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    stream_url: str = os.getenv("STREAM_URL", "ws://localhost:8765")
    triage: str = os.getenv("TRIAGE", "rules")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "") or "gpt-5.4-mini"
    openai_reasoning_effort: str = os.getenv("OPENAI_REASONING_EFFORT", "none")
    price_input_per_1m: float = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "0.75"))
    price_output_per_1m: float = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "4.50"))
    llm_budget_usd: float = float(os.getenv("LLM_BUDGET_USD", "1.00"))
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "10"))
    llm_chaos: str = os.getenv("LLM_CHAOS", "off")
    site_timezone: str = os.getenv("SITE_TIMEZONE", "America/New_York")
    escalation_window_s: float = float(os.getenv("ESCALATION_WINDOW_S", "120"))
    escalation_threshold: int = int(os.getenv("ESCALATION_THRESHOLD", "3"))
    camera_feeds_file: str = os.getenv("CAMERA_FEEDS_FILE", "feeds.json")
    camera_feed: str = os.getenv("CAMERA_FEED", "")
    camera_source: str = os.getenv("CAMERA_SOURCE", "")
    camera_id: str = os.getenv("CAMERA_ID", "cam-1")
    camera_site_id: str = os.getenv("CAMERA_SITE_ID", "site-101")
    camera_zone: str = os.getenv("CAMERA_ZONE", "custom-camera")
    camera_fps: float = float(os.getenv("CAMERA_FPS", "4"))
    camera_confidence: float = float(os.getenv("CAMERA_CONFIDENCE", "0.45"))
    camera_loiter_s: float = float(os.getenv("CAMERA_LOITER_S", "15"))
    camera_model: str = os.getenv("CAMERA_MODEL", "models/yolo26n.onnx")


settings = Settings()
SNAPSHOT_DIR = ROOT / "data" / "snapshots"


def resolve(path: str) -> str:
    candidate = ROOT / path
    return str(candidate) if candidate.exists() else path


def load_feeds() -> list[dict]:
    """Camera feeds from feeds.json whose source exists, plus CAMERA_SOURCE (e.g. an RTSP URL) if set."""
    feeds = []
    path = ROOT / settings.camera_feeds_file
    if path.is_file():
        for feed in json.loads(path.read_text(encoding="utf-8")):
            if (ROOT / feed["source"]).is_file() or "://" in feed["source"]:
                feeds.append(feed)
    if settings.camera_source:
        feeds.insert(0, {
            "id": "custom", "name": settings.camera_zone, "zone": settings.camera_zone,
            "source": settings.camera_source,
        })
    return feeds


def initial_feed(feeds: list[dict]) -> dict | None:
    if settings.camera_feed == "off" or not feeds:
        return None
    return next((f for f in feeds if f["id"] == settings.camera_feed), feeds[0])


def camera_config(feed: dict) -> dict:
    return {
        "source": resolve(feed["source"]),
        "camera_id": settings.camera_id,
        "site_id": settings.camera_site_id,
        "zone": feed["zone"],
        "fps": settings.camera_fps,
        "confidence": settings.camera_confidence,
        "loiter_s": settings.camera_loiter_s,
        "model": resolve(settings.camera_model),
        "snapshot_dir": str(SNAPSHOT_DIR),
    }
