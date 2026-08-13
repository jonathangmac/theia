"""Storage layer — persists frames, scene logs, and outlier events."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SceneRecord:
    timestamp: str
    frame_index: int
    scene: str
    objects: list[str]
    activity_level: str
    is_outlier: bool
    outlier_reason: str
    confidence: float
    severity: str
    frame_path: str | None = None
    stream_name: str | None = None


class SceneLog:
    """Append-only JSONL log of all scene analyses."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.touch(exist_ok=True)

    def append(self, record: SceneRecord) -> None:
        with open(self.log_path, "a") as f:
            f.write(json.dumps(asdict(record), default=str) + "\n")

    def read_all(self) -> list[dict]:
        records = []
        with open(self.log_path) as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def get_outliers(self) -> list[dict]:
        return [r for r in self.read_all() if r.get("is_outlier")]


class FrameStore:
    """Manages frame file retention and paths."""

    def __init__(self, frames_dir: Path, retention: int = 50):
        self.frames_dir = frames_dir
        self.retention = retention
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        frames = sorted(self.frames_dir.glob("frame_*.jpg"))
        for old in frames[: -self.retention]:
            old.unlink(missing_ok=True)
