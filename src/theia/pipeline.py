"""Pipeline orchestrator — ties capture, analysis, storage, and alerting together.

Supports single and multi-camera operation with an embedding gate that skips
VLM calls when the scene hasn't visually changed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import structlog

from theia.alerting import Alert, AlertDispatcher
from theia.analysis import AnalysisContext, VLMAnalyser
from theia.analysis.gate import EmbeddingGate
from theia.capture import FrameCapture
from theia.config import Settings
from theia.storage import FrameStore, SceneLog, SceneRecord

log = structlog.get_logger()


@dataclass
class StreamConfig:
    """Configuration for a single video stream."""
    name: str
    url: str
    interval: int = 15


@dataclass
class PipelineStats:
    frames_captured: int = 0
    frames_processed: int = 0
    frames_skipped: int = 0
    outliers_detected: int = 0

    @property
    def skip_rate(self) -> float:
        total = self.frames_processed + self.frames_skipped
        return (self.frames_skipped / total * 100) if total > 0 else 0.0


class StreamPipeline:
    """Processes a single video stream: capture → gate → analyse → judge → store → alert."""

    def __init__(
        self,
        stream_config: StreamConfig,
        settings: Settings,
        scene_log: SceneLog,
        alerting: AlertDispatcher,
        on_scene: Callable[[SceneRecord, str], None] | None = None,
    ):
        self.stream_config = stream_config
        self.settings = settings
        self.name = stream_config.name
        self.capture = FrameCapture(settings.frames_dir / stream_config.name)
        self.analyser = VLMAnalyser(
            api_key=settings.api_key,
            base_url=settings.vlm_base_url,
            model=settings.vlm_model,
            reasoning_effort=settings.vlm_reasoning_effort,
            max_tokens=settings.vlm_max_tokens,
        )
        self.gate = EmbeddingGate(threshold=settings.gate_threshold)
        self.context = AnalysisContext(history_size=settings.history_size)
        self.scene_log = scene_log
        self.frame_store = FrameStore(settings.frames_dir / stream_config.name)
        self.alerting = alerting
        self.on_scene = on_scene
        self.stats = PipelineStats()
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self) -> None:
        """Run the pipeline loop for this stream."""
        url = self.stream_config.url
        interval = self.stream_config.interval
        log.info("stream.start", stream=self.name, url=url, interval=interval)

        resolved_url = self._resolve(url)
        if not resolved_url:
            log.error("stream.resolve_failed", stream=self.name, url=url)
            return

        stream_url = resolved_url
        stream_url_age = 0
        frame_count = 0

        while not self._stop.is_set():
            if self.settings.max_frames and frame_count >= self.settings.max_frames:
                log.info("stream.complete", stream=self.name, stats=self.stats.__dict__)
                break

            # Refresh YouTube stream URL every 5 minutes
            if stream_url_age > 300 and "youtu" in url:
                log.info("stream.refreshing", stream=self.name)
                new_url = self._resolve(url)
                if new_url:
                    stream_url = new_url
                    stream_url_age = 0

            frame = self.capture.capture(stream_url, frame_count)
            if not frame:
                log.warn("stream.capture_failed", stream=self.name, frame=frame_count)
                stream_url_age += interval
                self._sleep(interval)
                continue

            stream_url_age += interval
            frame_count += 1
            self.stats.frames_captured += 1

            # Stage 0: Embedding gate — skip if scene hasn't changed
            gate_decision = self.gate.should_process(frame.path)
            if not gate_decision.should_process:
                self.stats.frames_skipped += 1
                log.info("stream.skipped", stream=self.name, frame=frame_count,
                         reason=gate_decision.reason)
                self._sleep(interval)
                continue

            # Stage 1+2: VLM analysis
            analysis = self.analyser.analyse_frame(frame.path, self.context)
            if not analysis:
                log.warn("stream.analysis_failed", stream=self.name, frame=frame_count)
                self._sleep(interval)
                continue

            self.stats.frames_processed += 1

            # Stage 3: LLM judge (on VLM flag or every 5th processed frame)
            vlm_flagged = analysis.is_outlier
            verdict = None
            if vlm_flagged or self.stats.frames_processed % 5 == 0:
                verdict = self.analyser.judge_outlier(analysis.scene, self.context)
                final_outlier = vlm_flagged or verdict.is_outlier
            else:
                final_outlier = vlm_flagged

            # Update rolling context
            self.context.add(frame.timestamp, analysis)

            # Build and store record
            severity = verdict.severity if verdict else "low"
            record = SceneRecord(
                timestamp=frame.timestamp,
                frame_index=frame_count,
                scene=analysis.scene,
                objects=analysis.objects,
                activity_level=analysis.activity_level,
                is_outlier=final_outlier,
                outlier_reason=(
                    verdict.reasoning if verdict and verdict.reasoning
                    else analysis.outlier_reason
                ),
                confidence=analysis.confidence,
                severity=severity,
                frame_path=str(frame.path) if final_outlier else None,
            )
            record.stream_name = self.name
            self.scene_log.append(record)

            # Alert if outlier
            if final_outlier:
                self.stats.outliers_detected += 1
                self.alerting.dispatch(Alert(
                    timestamp=frame.timestamp,
                    scene=analysis.scene,
                    severity=severity,
                    reasoning=record.outlier_reason,
                    frame_path=str(frame.path),
                ))

            log.info(
                "stream.frame",
                stream=self.name,
                frame=frame_count,
                time=frame.timestamp,
                scene=analysis.scene[:80],
                activity=analysis.activity_level,
                confidence=analysis.confidence,
                outlier=final_outlier,
                severity=severity if final_outlier else None,
                gate_distance=gate_decision.distance,
            )

            # Notify callback (for WebSocket/dashboard)
            if self.on_scene:
                try:
                    self.on_scene(record, self.name)
                except Exception:
                    pass

            # Cleanup old frames
            self.frame_store.cleanup()
            self._sleep(interval)

    def _resolve(self, url: str) -> str | None:
        if "youtu" in url:
            return self.capture.get_stream_url(url)
        return url

    def _sleep(self, seconds: int) -> None:
        """Sleep in small increments so stop() is responsive."""
        for _ in range(seconds):
            if self._stop.is_set():
                break
            time.sleep(1)


class MultiCameraPipeline:
    """Runs multiple StreamPipelines concurrently using threads."""

    def __init__(self, settings: Settings, on_scene: Callable[[SceneRecord, str], None] | None = None):
        self.settings = settings
        self.scene_log = SceneLog(settings.data_dir / "scenes.jsonl")
        self.alerting = AlertDispatcher(
            slack_webhook=settings.slack_webhook,
            alert_email=settings.alert_email,
        )
        self.on_scene = on_scene
        self.pipelines: dict[str, StreamPipeline] = {}
        self.threads: dict[str, threading.Thread] = {}

    def add_stream(self, name: str, url: str, interval: int | None = None) -> None:
        config = StreamConfig(
            name=name,
            url=url,
            interval=interval or self.settings.capture_interval,
        )
        pipeline = StreamPipeline(
            stream_config=config,
            settings=self.settings,
            scene_log=self.scene_log,
            alerting=self.alerting,
            on_scene=self.on_scene,
        )
        self.pipelines[name] = pipeline

    def start(self) -> None:
        """Start all stream pipelines in separate threads."""
        for name, pipeline in self.pipelines.items():
            thread = threading.Thread(target=pipeline.run, name=f"theia-{name}", daemon=True)
            thread.start()
            self.threads[name] = thread
            log.info("multi.started", stream=name)

    def stop(self) -> None:
        """Signal all pipelines to stop."""
        for pipeline in self.pipelines.values():
            pipeline.stop()
        for thread in self.threads.values():
            thread.join(timeout=5)
        log.info("multi.stopped")

    def stats(self) -> dict[str, dict]:
        return {name: p.stats.__dict__ for name, p in self.pipelines.items()}

    def is_running(self) -> bool:
        return any(t.is_alive() for t in self.threads.values())
