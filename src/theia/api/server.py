"""FastAPI server with WebSocket live updates and REST scene history."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from theia.config import Settings
from theia.pipeline import MultiCameraPipeline
from theia.storage import SceneLog, SceneRecord


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Theia — Live Outlier Monitor</title>
    <style>
        :root {
            --bg: #0a0e1a;
            --card: #121829;
            --border: #1e2a44;
            --text: #e0e6f0;
            --muted: #6b7689;
            --accent: #3b82f6;
            --danger: #ef4444;
            --warn: #f59e0b;
            --ok: #10b981;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            padding: 20px;
        }
        h1 { font-size: 1.4rem; margin-bottom: 4px; }
        h1 span { color: var(--accent); }
        .subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 20px; }
        .grid {
            display: grid;
            grid-template-columns: 1fr 350px;
            gap: 16px;
            height: calc(100vh - 100px);
        }
        .feed {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow-y: auto;
            padding: 12px;
        }
        .feed-header {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--muted);
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
        }
        .scene-card {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            margin-bottom: 10px;
            transition: border-color 0.2s;
        }
        .scene-card.outlier { border-color: var(--danger); }
        .scene-card.outlier .badge { background: var(--danger); }
        .scene-card .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }
        .scene-card .time { color: var(--muted); font-size: 0.75rem; }
        .scene-card .stream {
            color: var(--accent);
            font-size: 0.75rem;
            font-weight: 600;
        }
        .scene-card .badge {
            background: var(--ok);
            color: #fff;
            font-size: 0.65rem;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            font-weight: 700;
        }
        .scene-card .scene-text { font-size: 0.85rem; line-height: 1.4; margin-bottom: 6px; }
        .scene-card .objects {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }
        .scene-card .obj {
            background: var(--border);
            color: var(--muted);
            font-size: 0.7rem;
            padding: 2px 8px;
            border-radius: 3px;
        }
        .scene-card .reason {
            margin-top: 6px;
            font-size: 0.8rem;
            color: var(--danger);
        }
        .sidebar {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .stats-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
        }
        .stats-card h3 {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--muted);
            margin-bottom: 12px;
        }
        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            font-size: 0.85rem;
            border-bottom: 1px solid var(--border);
        }
        .stat-row:last-child { border: none; }
        .stat-val { font-weight: 700; color: var(--accent); }
        .stat-val.danger { color: var(--danger); }
        .status-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--ok);
            margin-right: 6px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .empty { color: var(--muted); text-align: center; padding: 40px; font-size: 0.85rem; }
    </style>
</head>
<body>
    <h1><span>Theia</span> Live Outlier Monitor</h1>
    <p class="subtitle">Real-time video analysis — <span id="status"><span class="status-dot"></span>Connected</span></p>
    <div class="grid">
        <div class="feed" id="feed">
            <div class="feed-header">
                <span>Scene Feed</span>
                <span id="frame-count">0 frames</span>
            </div>
            <div id="scenes">
                <div class="empty">Waiting for first frame...</div>
            </div>
        </div>
        <div class="sidebar">
            <div class="stats-card">
                <h3>Pipeline Stats</h3>
                <div id="stats-body">
                    <div class="stat-row"><span>Captured</span><span class="stat-val" id="s-captured">0</span></div>
                    <div class="stat-row"><span>Processed</span><span class="stat-val" id="s-processed">0</span></div>
                    <div class="stat-row"><span>Skipped (gate)</span><span class="stat-val" id="s-skipped">0</span></div>
                    <div class="stat-row"><span>Outliers</span><span class="stat-val danger" id="s-outliers">0</span></div>
                    <div class="stat-row"><span>Skip rate</span><span class="stat-val" id="s-skiprate">0%</span></div>
                </div>
            </div>
            <div class="stats-card">
                <h3>Active Streams</h3>
                <div id="streams-body">
                    <div class="empty" style="padding:10px">No streams</div>
                </div>
            </div>
            <div class="stats-card">
                <h3>Outlier Log</h3>
                <div id="outliers-body" style="max-height:300px;overflow-y:auto">
                    <div class="empty" style="padding:10px">No outliers detected</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const ws = new WebSocket(`ws://${location.host}/ws`);
        let frameCount = 0;
        let outlierCount = 0;
        const stats = { captured: 0, processed: 0, skipped: 0, outliers: 0 };

        ws.onopen = () => { document.getElementById('status').innerHTML = '<span class="status-dot"></span>Connected'; };
        ws.onclose = () => { document.getElementById('status').innerHTML = 'Disconnected'; };
        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'scene') addScene(msg.data);
            else if (msg.type === 'stats') updateStats(msg.data);
            else if (msg.type === 'outlier') addOutlier(msg.data);
        };

        function addScene(data) {
            frameCount++;
            document.getElementById('frame-count').textContent = frameCount + ' frames';
            const container = document.getElementById('scenes');
            if (frameCount === 1) container.innerHTML = '';

            const card = document.createElement('div');
            card.className = 'scene-card' + (data.is_outlier ? ' outlier' : '');
            const objects = (data.objects || []).map(o => `<span class="obj">${o}</span>`).join('');
            const badge = data.is_outlier
                ? `<span class="badge">${data.severity || 'outlier'}</span>`
                : `<span class="badge" style="background:var(--ok)">normal</span>`;
            const reason = data.is_outlier && data.outlier_reason
                ? `<div class="reason">${data.outlier_reason}</div>` : '';

            card.innerHTML = `
                <div class="header">
                    <div><span class="stream">${data.stream_name || 'camera'}</span></div>
                    <div><span class="time">${data.timestamp}</span> ${badge}</div>
                </div>
                <div class="scene-text">${data.scene}</div>
                <div class="objects">${objects}</div>
                ${reason}
            `;
            container.prepend(card);

            // Keep feed manageable
            while (container.children.length > 50) container.lastChild.remove();
        }

        function addOutlier(data) {
            outlierCount++;
            document.getElementById('s-outliers').textContent = outlierCount;
            const container = document.getElementById('outliers-body');
            if (outlierCount === 1) container.innerHTML = '';
            const item = document.createElement('div');
            item.className = 'scene-card outlier';
            item.style.marginBottom = '6px';
            item.innerHTML = `
                <div class="header">
                    <span class="stream">${data.stream_name || 'camera'}</span>
                    <span class="time">${data.timestamp}</span>
                </div>
                <div class="scene-text">${data.scene}</div>
            `;
            container.prepend(item);
            while (container.children.length > 20) container.lastChild.remove();
        }

        function updateStats(data) {
            document.getElementById('s-captured').textContent = data.captured || 0;
            document.getElementById('s-processed').textContent = data.processed || 0;
            document.getElementById('s-skipped').textContent = data.skipped || 0;
            document.getElementById('s-outliers').textContent = data.outliers || 0;
            const total = (data.processed || 0) + (data.skipped || 0);
            const rate = total > 0 ? Math.round(data.skipped / total * 100) : 0;
            document.getElementById('s-skiprate').textContent = rate + '%';
        }
    </script>
</body>
</html>"""


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


def create_app(settings: Settings, streams: list[tuple[str, str]] | None = None) -> FastAPI:
    """Create the FastAPI app with pipeline integration."""
    app = FastAPI(title="Theia", docs_url="/docs")
    manager = ConnectionManager()
    scene_log = SceneLog(settings.data_dir / "scenes.jsonl")

    pipeline = MultiCameraPipeline(settings)

    def on_scene(record: SceneRecord, stream_name: str):
        """Callback when a new scene is analysed — broadcasts to WebSocket clients."""
        data = {
            "type": "scene",
            "data": {
                "timestamp": record.timestamp,
                "frame_index": record.frame_index,
                "scene": record.scene,
                "objects": record.objects,
                "activity_level": record.activity_level,
                "is_outlier": record.is_outlier,
                "outlier_reason": record.outlier_reason,
                "confidence": record.confidence,
                "severity": record.severity,
                "stream_name": stream_name,
            },
        }
        if record.is_outlier:
            outlier_data = {**data["data"], "type": "outlier"}
            asyncio.run(manager.broadcast({"type": "outlier", "data": data["data"]}))
        asyncio.run(manager.broadcast(data))

    if streams:
        for name, url in streams:
            pipeline.add_stream(name, url)
    else:
        for i, url in enumerate(settings.stream_list):
            pipeline.add_stream(f"camera-{i+1}", url)

    @app.on_event("startup")
    def _startup():
        pipeline.start()

    @app.on_event("shutdown")
    def _shutdown():
        pipeline.stop()

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return DASHBOARD_HTML

    @app.get("/api/scenes")
    async def get_scenes(limit: int = 50):
        records = scene_log.read_all()
        return JSONResponse(records[-limit:])

    @app.get("/api/outliers")
    async def get_outliers(limit: int = 50):
        outliers = scene_log.get_outliers()
        return JSONResponse(outliers[-limit:])

    @app.get("/api/stats")
    async def get_stats():
        return JSONResponse(pipeline.stats())

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)

    return app
