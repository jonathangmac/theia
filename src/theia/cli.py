"""CLI entry point for Theia."""

from __future__ import annotations

import argparse
import sys

import structlog

from theia.config import get_settings
from theia.pipeline import MultiCameraPipeline

log = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(
        prog="theia",
        description="Theia — Real-time video outlier detection",
    )
    sub = parser.add_subparsers(dest="command")

    # --- run ---
    run_parser = sub.add_parser("run", help="Run the pipeline")
    run_parser.add_argument(
        "--stream", "-s", type=str, action="append", default=[],
        help="Stream URL (YouTube or direct). Can be repeated for multi-camera.",
    )
    run_parser.add_argument(
        "--name", "-n", type=str, action="append", default=[],
        help="Name for the stream (paired with --stream).",
    )
    run_parser.add_argument("--interval", type=int, default=None, help="Seconds between frames.")
    run_parser.add_argument("--max-frames", type=int, default=None, help="Stop after N frames.")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")

    # --- dashboard ---
    dash_parser = sub.add_parser("dashboard", help="Run the web dashboard")
    dash_parser.add_argument("--host", default="0.0.0.0", help="Bind address.")
    dash_parser.add_argument("--port", "-p", type=int, default=8000, help="Port.")
    dash_parser.add_argument("--stream", "-s", type=str, action="append", default=[])
    dash_parser.add_argument("--name", "-n", type=str, action="append", default=[])
    dash_parser.add_argument("--interval", type=int, default=None)
    dash_parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            10 if getattr(args, "verbose", False) else 20
        )
    )

    settings = get_settings()
    if hasattr(args, "interval") and args.interval:
        settings.capture_interval = args.interval
    if hasattr(args, "max_frames") and args.max_frames is not None:
        settings.max_frames = args.max_frames

    if not settings.api_key:
        print("ERROR: Set TENSORX_API_KEY in .env or environment", file=sys.stderr)
        sys.exit(1)

    settings.frames_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "run":
        _run_pipeline(args, settings)
    elif args.command == "dashboard":
        _run_dashboard(args, settings)


def _build_streams(args, settings) -> list[tuple[str, str]]:
    """Return list of (name, url) pairs from args or config."""
    if args.stream:
        names = args.name if args.name else []
        streams = []
        for i, url in enumerate(args.stream):
            name = names[i] if i < len(names) else f"camera-{i+1}"
            streams.append((name, url))
        return streams
    else:
        urls = settings.stream_list
        return [(f"camera-{i+1}", url) for i, url in enumerate(urls)]


def _run_pipeline(args, settings):
    streams = _build_streams(args, settings)
    pipeline = MultiCameraPipeline(settings)

    for name, url in streams:
        pipeline.add_stream(name, url)

    pipeline.start()
    log.info("cli.running", streams=[n for n, _ in streams])

    try:
        import time
        while pipeline.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        pipeline.stop()


def _run_dashboard(args, settings):
    try:
        from theia.api.server import create_app
    except ImportError:
        print("Install API dependencies: pip install -e '.[api]'", file=sys.stderr)
        sys.exit(1)

    streams = _build_streams(args, settings) if args.stream else None
    app = create_app(settings, streams)
    log.info("cli.dashboard", host=args.host, port=args.port)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
