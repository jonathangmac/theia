# Theia

Real-time video outlier detection. Streams live video, analyses scenes with vision-language models, and flags anomalous behaviour with text-based synopses.

## Quick Start

```bash
# 1. Clone and set up
git clone <repo-url> theia
cd theia
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env — add your TENSORX_API_KEY

# 3. Run
theia --stream "https://youtu.be/3nyPER2kzqk" --interval 15

# Or run for a fixed number of frames
theia --max-frames 10 --interval 10
```

## Docker

```bash
cp .env.example .env
# Edit .env
docker compose up -d
```

## Architecture

```
Video Stream → Frame Capture → VLM Analysis → Outlier Judge → Storage + Alerts
     │              │              │               │                │
   yt-dlp        ffmpeg        Kimi K3        Kimi K3          JSONL + Slack
   resolves      grabs         describes      compares         (configurable)
   stream URL    frames        scene          to baseline
```

### Three-stage pipeline

1. **Frame Capture** — `yt-dlp` resolves the live stream URL, `ffmpeg` grabs a frame every N seconds
2. **VLM Analysis** — Kimi K3 (via TensorX) describes the scene, detects objects, and flags potential outliers against a rolling baseline
3. **Outlier Judge** — A second LLM pass verifies flagged outliers, comparing against recent scene history to reduce false positives

### What counts as an outlier?

- Sudden crowd formation or dispersal
- Running, falling, fighting, or erratic movement
- Emergency vehicles or reversed traffic flow
- Unusual object placement or loitering
- Altered pedestrian patterns deviating from baseline

## Configuration

All settings via environment variables or `.env` file (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `TENSORX_API_KEY` | — | API key for TensorX inference |
| `THEIA_VLM_MODEL` | `moonshotai/kimi-k3` | Vision-language model |
| `THEIA_CAPTURE_INTERVAL` | `15` | Seconds between frames |
| `THEIA_HISTORY_SIZE` | `10` | Scenes kept as baseline |
| `THEIA_STREAMS` | Dublin cam URL | Comma-separated stream URLs |
| `THEIA_SLACK_WEBHOOK` | — | Slack webhook for alerts |

## Project Structure

```
src/theia/
├── capture/     Frame capture from YouTube/RTSP streams
├── analysis/    VLM scene description + outlier detection
├── storage/     Scene logging and frame retention
├── alerting/    Webhook/email alert dispatch
├── pipeline.py  Orchestrates the full loop
├── config.py    Pydantic settings from env vars
└── cli.py       CLI entry point
```

## Data Output

- `data/scenes.jsonl` — append-only log of all scene analyses
- `data/frames/` — captured frame images (configurable retention)
- Slack/webhook — real-time alerts for detected outliers

## Requirements

- Python 3.11+
- ffmpeg (for frame capture)
- yt-dlp (for YouTube stream resolution)
- TensorX API key (or any OpenAI-compatible VLM provider)

## License

Proprietary. All rights reserved.
