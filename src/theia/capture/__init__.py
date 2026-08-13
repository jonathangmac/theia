"""Frame capture from live video sources."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CapturedFrame:
    path: Path
    timestamp: str
    stream_url: str
    frame_index: int


class FrameCapture:
    """Captures individual frames from YouTube live streams or direct URLs."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_stream_url(self, youtube_url: str) -> str | None:
        """Use yt-dlp to resolve a direct stream URL from a YouTube link."""
        try:
            result = subprocess.run(
                [
                    "yt-dlp", "-f", "best[height<=720]",
                    "-g", "--no-warnings", youtube_url,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            url = result.stdout.strip().split("\n")[0]
            return url if url.startswith("http") else None
        except Exception:
            return None

    def capture(
        self,
        stream_url: str,
        frame_index: int,
        timeout: int = 15,
    ) -> CapturedFrame | None:
        """Grab a single frame from a live stream via ffmpeg."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        output_path = self.output_dir / f"frame_{frame_index:06d}.jpg"

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-timeout", "5000000",
                    "-i", stream_url,
                    "-frames:v", "1", "-q:v", "2",
                    str(output_path),
                ],
                capture_output=True,
                timeout=timeout,
            )
        except Exception:
            return None

        if output_path.exists() and output_path.stat().st_size > 1000:
            return CapturedFrame(
                path=output_path,
                timestamp=timestamp,
                stream_url=stream_url,
                frame_index=frame_index,
            )
        return None

    def cleanup_old_frames(self, keep: int = 50) -> None:
        """Remove old frames beyond the retention count."""
        frames = sorted(self.output_dir.glob("frame_*.jpg"))
        for old in frames[:-keep]:
            old.unlink(missing_ok=True)
