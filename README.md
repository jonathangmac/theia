# Theia

Real-time video outlier detection. Streams live video, analyses scenes with vision-language models, and flags anomalous behaviour with text-based synopses.

## Quick Start

```bash
# 1. Clone and set up
git clone https://github.com/jonathangmac/theia.git
cd theia
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"

# 2. Configure
cp .env.example .env
# Edit .env — add your TENSORX_API_KEY

# 3. Run the CLI pipeline
theia run --stream "https://youtu.be/3nyPER2kzqk" --name "dublin" --interval 15

# Or launch the web dashboard
theia dashboard --stream "https://youtu.be/3nyPER2kzqk" --name "dublin" --port 8000
# Open http://localhost:8000
```

## Features

- **Live video capture** — YouTube live streams and RTSP cameras via yt-dlp + ffmpeg
- **VLM scene analysis** — Kimi K3 describes scenes, detects objects, flags anomalies
- **Embedding gate** — Perceptual hash skips VLM calls when the scene hasn't changed (saves API costs)
- **Outlier judge** — Second-pass LLM verification with rolling baseline context reduces false positives
- **Multi-camera** — Run multiple streams in parallel with independent baselines
- **Web dashboard** — Live scene feed, outlier alerts, and pipeline stats via WebSocket
- **Alerting** — Slack webhook integration for real-time outlier notifications
- **Storage** — Append-only JSONL scene log with frame retention

## Architecture

```
Video Stream → Frame Capture → Embedding Gate → VLM Analysis → Outlier Judge → Storage + Alerts
     │              │              │               │               │                │
   yt-dlp        ffmpeg        pHash          Kimi K3        Kimi K3          JSONL + Slack
   resolves      grabs         skip if        describes      compares          + WebSocket
   stream URL    frames        unchanged      scene          to baseline        (dashboard)
```

### Four-stage pipeline

1. **Frame Capture** — `yt-dlp` resolves the stream URL, `ffmpeg` grabs a frame every N seconds
2. **Embedding Gate** — Perceptual hash (pHash) compares frames; if the scene hasn't changed, skips the VLM call entirely (zero cost)
3. **VLM Analysis** — Kimi K3 (via TensorX) describes the scene, detects objects, and flags potential outliers
4. **Outlier Judge** — Second LLM pass verifies flagged outliers against recent scene history

### What counts as an outlier?

- Sudden crowd formation or dispersal
- Running, falling, fighting, or erratic movement
- Emergency vehicles or reversed traffic flow
- Unusual object placement or loitering
- Altered pedestrian patterns deviating from baseline

## Multi-Camera

Run multiple streams simultaneously — each gets its own baseline context:

```bash
theia run \
  --stream "https://youtu.be/3nyPER2kzqk" --name "dublin" \
  --stream "https://youtu.be/ANOTHER_URL" --name "camera-2" \
  --interval 15
```

## Web Dashboard

```bash
theia dashboard --stream "https://youtu.be/3nyPER2kzqk" --name "dublin" --port 8000
```

- **Live scene feed** — WebSocket-streamed scene descriptions with objects and confidence
- **Outlier alerts** — Highlighted in red with severity and reasoning
- **Pipeline stats** — Frames captured, processed, skipped (gate savings), outliers detected
- **REST API** — `/api/scenes`, `/api/outliers`, `/api/stats`

## Configuration

All settings via environment variables or `.env` file (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `TENSORX_API_KEY` | — | API key for TensorX inference |
| `THEIA_VLM_MODEL` | `moonshotai/kimi-k3` | Vision-language model |
| `THEIA_VLM_BASE_URL` | `https://api.tensorx.ai/v1` | OpenAI-compatible API endpoint |
| `THEIA_VLM_REASONING_EFFORT` | `low` | Kimi K3 reasoning depth |
| `THEIA_CAPTURE_INTERVAL` | `15` | Seconds between frames |
| `THEIA_HISTORY_SIZE` | `10` | Scenes kept as baseline |
| `THEIA_GATE_THRESHOLD` | `15` | pHash Hamming distance — lower = more sensitive |
| `THEIA_STREAMS` | Dublin cam | Comma-separated stream URLs |
| `THEIA_SLACK_WEBHOOK` | — | Slack webhook for alerts |

## Docker

```bash
cp .env.example .env
# Edit .env
docker compose up -d
```

## Project Structure

```
src/theia/
├── capture/          Frame capture from YouTube/RTSP streams
├── analysis/         VLM scene description + outlier detection
│   ├── __init__.py   VLM analyser + outlier judge
│   └── gate.py       Perceptual hash embedding gate
├── storage/          Scene logging and frame retention
├── alerting/         Webhook/email alert dispatch
├── api/              FastAPI dashboard with WebSocket
│   └── server.py     REST + WebSocket server
├── pipeline.py        Multi-camera orchestrator with threads
├── config.py          Pydantic settings from env vars
└── cli.py             CLI entry point (run / dashboard)
```

## Data Output

- `data/scenes.jsonl` — Append-only log of all scene analyses
- `data/frames/<stream>/` — Captured frame images per stream (configurable retention)
- Slack webhook — Real-time alerts for detected outliers
- WebSocket — Live updates to the dashboard

## Requirements

- Python 3.11+
- ffmpeg (for frame capture)
- yt-dlp (for YouTube stream resolution)
- TensorX API key (or any OpenAI-compatible VLM provider)

## License

Proprietary. All rights reserved.
