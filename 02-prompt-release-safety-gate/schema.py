"""Response contract for the CRM summary feature (Pydantic-style, stdlib only)."""

from __future__ import annotations

import json
from dataclasses import dataclass

SENTIMENTS = {"positive", "neutral", "negative"}
URGENCIES = {"low", "medium", "high"}
MAX_SUMMARY_WORDS = 40


@dataclass
class CRMSummary:
    summary: str
    sentiment: str
    next_action: str
    urgency: str
    confidence: float


def parse_output(raw: str) -> tuple[CRMSummary | None, list[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, ["output is not pure JSON"]
    errors = []
    for key, typ in (("summary", str), ("sentiment", str), ("next_action", str), ("urgency", str), ("confidence", (int, float))):
        if not isinstance(data.get(key), typ):
            errors.append(f"missing or invalid field: {key}")
    if errors:
        return None, errors
    if data["sentiment"] not in SENTIMENTS:
        errors.append(f"sentiment not in {sorted(SENTIMENTS)}")
    if data["urgency"] not in URGENCIES:
        errors.append(f"urgency not in {sorted(URGENCIES)}")
    if not 0 <= data["confidence"] <= 1:
        errors.append("confidence outside [0, 1]")
    if len(data["summary"].split()) > MAX_SUMMARY_WORDS:
        errors.append(f"summary longer than {MAX_SUMMARY_WORDS} words")
    if errors:
        return None, errors
    return CRMSummary(**{k: data[k] for k in CRMSummary.__dataclass_fields__}), []
