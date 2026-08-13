"""Configuration via environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="THEIA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Inference — TENSORX_API_KEY has no THEIA_ prefix
    tensorx_api_key: str = Field(default="", validation_alias="TENSORX_API_KEY")
    vlm_model: str = "moonshotai/kimi-k3"
    vlm_base_url: str = "https://api.tensorx.ai/v1"
    vlm_reasoning_effort: str = "low"
    vlm_max_tokens: int = 2000

    # Pipeline
    capture_interval: int = 15
    history_size: int = 10
    max_frames: int = 0
    gate_threshold: int = 15

    # Streams
    streams: str = "https://youtu.be/3nyPER2kzqk"

    # Storage
    db_url: str = "sqlite+aiosqlite:///data/theia.db"

    # Alerting
    slack_webhook: str = ""
    alert_email: str = ""

    # Paths
    data_dir: Path = Path("data")
    frames_dir: Path = Path("data/frames")

    @property
    def api_key(self) -> str:
        return self.tensorx_api_key

    @property
    def stream_list(self) -> list[str]:
        return [s.strip() for s in self.streams.split(",") if s.strip()]


def get_settings() -> Settings:
    return Settings()
