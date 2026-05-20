"""SecretScrubber — redact secrets from content strings without mutating input."""

import os
import tempfile
from dataclasses import dataclass

from detect_secrets import SecretsCollection
from detect_secrets.settings import transient_settings

from pr_reviewer.logging import get_logger

_logger = get_logger(__name__)

_REDACTED = "[REDACTED]"

_PLUGINS: list[dict] = [
    {"name": "AWSKeyDetector"},
    {"name": "GitHubTokenDetector"},
    {"name": "GitLabTokenDetector"},
    {"name": "PrivateKeyDetector"},
    {"name": "SlackDetector"},
    {"name": "StripeDetector"},
    {"name": "TwilioKeyDetector"},
    {"name": "KeywordDetector"},
    {"name": "HexHighEntropyString", "limit": 3.0},
    {"name": "Base64HighEntropyString", "limit": 4.5},
]


@dataclass(frozen=True)
class Detection:
    secret_type: str
    line_number: int


class SecretScrubber:
    def scrub(
        self,
        content: str,
        source: str = "diff",
        corpus: str | None = None,
        entry_id: str | None = None,
    ) -> tuple[str, list[Detection]]:
        if not content:
            return content, []

        detections: list[Detection] = []
        secret_values: list[str] = []

        with transient_settings({"plugins_used": _PLUGINS}):
            sc = SecretsCollection()
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".txt",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                sc.scan_file(tmp_path)
            finally:
                os.unlink(tmp_path)

        for _, secret in sc:
            if secret.secret_value is None:
                continue
            detections.append(Detection(secret_type=secret.type, line_number=secret.line_number))
            secret_values.append(secret.secret_value)

        if detections and source == "kb":
            _logger.error(
                f"Secret detected in KB entry: corpus={corpus} entry_id={entry_id}"
                f" count={len(detections)}"
            )

        redacted = content
        for val in secret_values:
            redacted = redacted.replace(val, _REDACTED)

        return redacted, detections
