"""Pipeline orchestrator — ties capture, analysis, storage, and alerting together."""

from __future__ import annotations

import time
from datetime import datetime

import structlog

from theia.alerting import Alert, AlertDispatcher
from theia.analysis import AnalysisContext, VLMAnalyser
from theia.capture import FrameCapture
from theia.config import Settings
from theia.storage import FrameStore, SceneLog, SceneRecord

log = structlog.get_logger()


class Pipeline:
    """Main processing loop: capture → analyse → judge → store → alert."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.capture = FrameCapture(settings.frames_dir)
        self.analyser = VLMAnalyser(
            api_key=settings.api_key,
            base_url=settings.vlm_base_url,
            model=settings.vlm_model,
            reasoning_effort=settings.vlm_reasoning_effort,
            max_tokens=settings.vlm_max_tokens,
        )
        self.context = AnalysisContext(history_size=settings.history_size)
        self.scene_log = SceneLog(settings.data_dir / "scenes.jsonl")
        self.frame_store = FrameStore(settings.frames_dir)
        self.alerting = AlertDispatcher(
            slack_webhook=settings.slack_webhook,
            alert_email=settings.alert_email,
        )

    def run(self, stream_url: str | None = None) -> None:
        """Run the pipeline loop on a single stream."""
        url = stream_url or self.settings.stream_list[0]
        log.info("pipeline.start", stream=url, interval=self.settings.capture_interval)

        # Resolve YouTube URL to direct stream
        if "youtu" in url:
            log.info("pipeline.resolving_stream", url=url)
            resolved = self.capture.get_stream_url(url)
            if not resolved:
                log.error("pipeline.resolve_failed", url=url)
                return
            stream_url = resolved
        else:
            stream_url = url

        stream_url_age = 0
        frame_count = 0
        outlier_count = 0

        while True:
            if self.settings.max_frames and frame_count >= self.settings.max_frames:
                log.info("pipeline.complete", frames=frame_count, outliers=outlier_count)
                break

            # Refresh YouTube stream URL every 5 minutes
            if stream_url_age > 300 and "youtu" in url:
                log.info("pipeline.refreshing_stream")
                new_url = self.capture.get_stream_url(url)
                if new_url:
                    stream_url = new_url
                    stream_url_age = 0
                else:
                    log.warn("pipeline.refresh_failed")

            frame = self.capture.capture(stream_url, frame_count)
            if not frame:
                log.warn("pipeline.capture_failed", frame=frame_count)
                stream_url_age += self.settings.capture_interval
                time.sleep(self.settings.capture_interval)
                continue

            stream_url_age += self.settings.capture_interval
            frame_count += 1

            # Stage 1+2: VLM analysis
            analysis = self.analyser.analyse_frame(frame.path, self.context)
            if not analysis:
                log.warn("pipeline.analysis_failed", frame=frame_count)
                time.sleep(self.settings.capture_interval)
                continue

            # Stage 3: LLM judge (on VLM flag or every 5th frame)
            vlm_flagged = analysis.is_outlier
            verdict = None
            if vlm_flagged or frame_count % 5 == 0:
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
            self.scene_log.append(record)

            # Alert if outlier
            if final_outlier:
                outlier_count += 1
                self.alerting.dispatch(Alert(
                    timestamp=frame.timestamp,
                    scene=analysis.scene,
                    severity=severity,
                    reasoning=record.outlier_reason,
                    frame_path=str(frame.path),
                ))

            log.info(
                "pipeline.frame",
                frame=frame_count,
                time=frame.timestamp,
                scene=analysis.scene,
                activity=analysis.activity_level,
                confidence=analysis.confidence,
                outlier=final_outlier,
                severity=severity if final_outlier else None,
            )

            # Cleanup old frames
            self.frame_store.cleanup()

            time.sleep(self.settings.capture_interval)
