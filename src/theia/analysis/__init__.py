"""VLM-based scene analysis and outlier detection."""

from __future__ import annotations

import base64
import json
from collections import deque
from dataclasses import dataclass, field

from openai import OpenAI

SYSTEM_PROMPT = """\
You are a video surveillance analyst. You receive frames from a live camera \
feed and must produce a concise scene description and an outlier assessment.

You ALWAYS respond in valid JSON with this schema:
{
  "scene": "1-2 sentence description of what is happening",
  "objects": ["list of notable objects/persons/vehicles detected"],
  "activity_level": "low | moderate | high",
  "is_outlier": true/false,
  "outlier_reason": "why this is unusual, or empty string if not",
  "confidence": 0.0-1.0
}

An "outlier" is any behaviour that deviates from normal activity for the \
time and location. Examples: someone running (not walking), a vehicle \
driving erratically, a crowd forming suddenly, someone loitering unusually, \
an emergency vehicle, altered pedestrian patterns, unusual object placement.

Be conservative — only flag true outliers, not routine traffic or weather.\
"""

JUDGE_PROMPT = """\
You are a behavioural analyst reviewing a log of scene descriptions from a \
live camera feed. Given the recent history of scenes and a new scene, decide \
whether the new scene represents an outlier.

Consider patterns: time-of-day expectations, recurring activities, gradual \
changes vs. sudden deviations. A sudden crowd, reversed traffic direction, \
running, falling, fighting, or emergency vehicles are outliers. Normal \
traffic flow, weather shifts, and routine pedestrian movement are NOT.

Respond in valid JSON:
{
  "is_outlier": true/false,
  "reasoning": "1 sentence explanation",
  "severity": "low | medium | high"
}
"""


@dataclass
class SceneAnalysis:
    scene: str
    objects: list[str]
    activity_level: str
    is_outlier: bool
    outlier_reason: str
    confidence: float


@dataclass
class OutlierVerdict:
    is_outlier: bool
    reasoning: str
    severity: str


@dataclass
class AnalysisContext:
    """Rolling history of scene descriptions for baseline comparison."""
    history: deque = field(default_factory=lambda: deque(maxlen=10))

    def __init__(self, history_size: int = 10):
        self.history = deque(maxlen=history_size)

    def add(self, timestamp: str, analysis: SceneAnalysis) -> None:
        self.history.append({
            "time": timestamp,
            "scene": analysis.scene,
            "objects": analysis.objects,
            "activity_level": analysis.activity_level,
        })

    def format_history(self) -> str:
        if not self.history:
            return "  (no prior data — establishing baseline)"
        return "\n".join(
            f"  - [{h['time']}] {h['scene']} (objects: {', '.join(h['objects'])})"
            for h in self.history
        )


class VLMAnalyser:
    """Analyse frames using a vision-language model via OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str = "low",
        max_tokens: int = 2000,
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens

    def _encode_image(self, image_path) -> str:
        import pathlib
        p = pathlib.Path(image_path)
        return base64.b64encode(p.read_bytes()).decode()

    def analyse_frame(self, image_path, context: AnalysisContext) -> SceneAnalysis | None:
        """Stage 1+2: VLM describes the scene and flags potential outliers."""
        b64 = self._encode_image(image_path)

        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            },
            {
                "type": "text",
                "text": (
                    f"Analyse this frame from a live camera.\n\n"
                    f"Recent activity log:\n{context.format_history()}\n\n"
                    f"Describe the current scene and determine if it is an outlier. "
                    f"Respond in JSON only."
                ),
            },
        ]

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
                extra_body={"reasoning_effort": self.reasoning_effort},
            )
            data = json.loads(resp.choices[0].message.content)
            return SceneAnalysis(
                scene=data.get("scene", ""),
                objects=data.get("objects", []),
                activity_level=data.get("activity_level", "unknown"),
                is_outlier=data.get("is_outlier", False),
                outlier_reason=data.get("outlier_reason", ""),
                confidence=float(data.get("confidence", 0.0)),
            )
        except Exception:
            return None

    def judge_outlier(
        self, current_scene: str, context: AnalysisContext
    ) -> OutlierVerdict:
        """Stage 3: Second-pass LLM judge for outlier verification."""
        if len(context.history) < 3:
            return OutlierVerdict(False, "Insufficient baseline", "low")

        history_text = "\n".join(
            f"  [{h['time']}] {h['scene']}" for h in context.history
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": JUDGE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Recent scene log:\n{history_text}\n\n"
                            f"New scene: {current_scene}\n\n"
                            f"Is this new scene an outlier? Respond in JSON."
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=1000,
                response_format={"type": "json_object"},
                extra_body={"reasoning_effort": self.reasoning_effort},
            )
            data = json.loads(resp.choices[0].message.content)
            return OutlierVerdict(
                is_outlier=data.get("is_outlier", False),
                reasoning=data.get("reasoning", ""),
                severity=data.get("severity", "low"),
            )
        except Exception as e:
            return OutlierVerdict(False, str(e), "low")
