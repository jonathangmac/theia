"""CLI entry point for Theia."""

from __future__ import annotations

import argparse
import sys

import structlog

from theia.config import get_settings
from theia.pipeline import Pipeline

log = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(
        prog="theia",
        description="Theia — Real-time video outlier detection",
    )
    parser.add_argument(
        "--stream",
        type=str,
        default=None,
        help="Stream URL (YouTube or direct). Defaults to config.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Seconds between frame captures.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Stop after N frames (0 = forever).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            10 if args.verbose else 20
        )
    )

    settings = get_settings()
    if args.interval:
        settings.capture_interval = args.interval
    if args.max_frames is not None:
        settings.max_frames = args.max_frames

    if not settings.api_key:
        print("ERROR: Set TENSORX_API_KEY in .env or environment", file=sys.stderr)
        sys.exit(1)

    settings.frames_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    pipeline = Pipeline(settings)
    try:
        pipeline.run(stream_url=args.stream)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        sys.exit(0)
