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
    openai_model: str = os.getenv("OPENAI_MODEL", "")
    llm_budget_usd: float = float(os.getenv("LLM_BUDGET_USD", "1.00"))


settings = Settings()
