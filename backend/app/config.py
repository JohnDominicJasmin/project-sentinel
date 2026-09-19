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
    camera_source: str = os.getenv("CAMERA_SOURCE", "")
    camera_id: str = os.getenv("CAMERA_ID", "cam-1")
    camera_site_id: str = os.getenv("CAMERA_SITE_ID", "site-101")
    camera_zone: str = os.getenv("CAMERA_ZONE", "parking-lot")
    camera_fps: float = float(os.getenv("CAMERA_FPS", "4"))
    camera_confidence: float = float(os.getenv("CAMERA_CONFIDENCE", "0.45"))
    camera_loiter_s: float = float(os.getenv("CAMERA_LOITER_S", "15"))
    camera_model: str = os.getenv("CAMERA_MODEL", "models/yolo26n.onnx")


settings = Settings()
SNAPSHOT_DIR = ROOT / "data" / "snapshots"


def resolve(path: str) -> str:
    candidate = ROOT / path
    return str(candidate) if candidate.exists() else path


def camera_config() -> dict:
    return {
        "source": resolve(settings.camera_source),
        "camera_id": settings.camera_id,
        "site_id": settings.camera_site_id,
        "zone": settings.camera_zone,
        "fps": settings.camera_fps,
        "confidence": settings.camera_confidence,
        "loiter_s": settings.camera_loiter_s,
        "model": resolve(settings.camera_model),
        "snapshot_dir": str(SNAPSHOT_DIR),
    }
