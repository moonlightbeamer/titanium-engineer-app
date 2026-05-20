"""Classical (non-LLM) metrics for the eval harness."""

from __future__ import annotations

from typing import Any

_REQUIRED_FIELDS = {"category", "file_path", "line_number", "explanation", "severity"}
_SECURITY_CATEGORIES = {"security"}


def validate_schema(finding: dict[str, Any]) -> bool:
    """Return True if *finding* contains all required fields."""
    return _REQUIRED_FIELDS.issubset(finding.keys())


def check_regex(finding: dict[str, Any]) -> bool:
    """Return False for security findings that lack a line number."""
    category = finding.get("category", "")
    line_number = finding.get("line_number")
    if category in _SECURITY_CATEGORIES and not line_number:
        return False
    return True


def token_f1(reference: str, prediction: str) -> float:
    """Token-level F1 between *reference* and *prediction* texts."""
    ref_tokens = set(reference.lower().split())
    pred_tokens = set(prediction.lower().split())
    if not ref_tokens or not pred_tokens:
        return 0.0
    common = ref_tokens & pred_tokens
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)
