"""Alerting — notifies on outlier detection via webhooks, email, etc."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass
class Alert:
    timestamp: str
    scene: str
    severity: str
    reasoning: str
    frame_path: str | None = None


class AlertDispatcher:
    """Routes outlier alerts to configured channels."""

    def __init__(self, slack_webhook: str = "", alert_email: str = ""):
        self.slack_webhook = slack_webhook
        self.alert_email = alert_email

    def dispatch(self, alert: Alert) -> None:
        if self.slack_webhook:
            self._send_slack(alert)
        # Email/other channels can be added here

    def _send_slack(self, alert: Alert) -> None:
        payload = {
            "text": (
                f":rotating_light: *Outlier Detected* [{alert.severity.upper()}]\n"
                f"*Time:* {alert.timestamp}\n"
                f"*Scene:* {alert.scene}\n"
                f"*Reason:* {alert.reasoning}"
            )
        }
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.slack_webhook,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
