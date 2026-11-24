"""Runtime configuration loaded from environment / .env (never hardcode secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    # strip inline comments like "VALUE   # note" that people copy from .env.example
    raw = os.getenv(name, default) or ""
    return raw.split(" #")[0].strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str
    matcher_mode: str
    vision_provider: str
    vision_model: str
    vision_concurrency: int
    vision_timeout_s: float
    anthropic_api_key: str = field(repr=False)
    openai_api_key: str = field(repr=False)
    gemini_api_key: str = field(repr=False)
    clip_model: str
    clip_pretrained: str
    detector: str
    cors_origins: list[str]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "scryfall.db"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def bulk_dir(self) -> Path:
        return self.data_dir / "bulk"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "art_index"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(_env("DATA_DIR", "./data"))
    if not data_dir.is_absolute():
        data_dir = (REPO_ROOT / data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        user_agent=_env("SCRYFALL_USER_AGENT", "BinderScanMTG/0.1 (local dev)"),
        matcher_mode=_env("MATCHER_MODE", "auto").lower(),
        vision_provider=_env("VISION_PROVIDER", "").lower(),
        vision_model=_env("VISION_MODEL", ""),
        vision_concurrency=int(_env("VISION_CONCURRENCY", "6") or 6),
        vision_timeout_s=float(_env("VISION_TIMEOUT_S", "45") or 45),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        openai_api_key=_env("OPENAI_API_KEY"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        clip_model=_env("CLIP_MODEL", "ViT-B-32"),
        clip_pretrained=_env("CLIP_PRETRAINED", "laion2b_s34b_b79k"),
        detector=_env("DETECTOR", "opencv").lower(),
        cors_origins=[o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    )
