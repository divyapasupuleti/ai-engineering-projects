"""Request complexity classifier -> routing tier (1 = cheap/simple, 3 = reasoning/high-risk)."""

from __future__ import annotations

import re
from dataclasses import dataclass

TIER1_VERBS = re.compile(r"\b(extract|format|convert|reformat|list|fix grammar|translate to json)\b", re.I)
TIER2_VERBS = re.compile(r"\b(summari[sz]e|classify|categori[sz]e|rewrite|tag|translate)\b", re.I)
TIER3_VERBS = re.compile(r"\b(analy[sz]e|reason|plan|compare|evaluate|negotiate|diagnose|why)\b", re.I)
HIGH_RISK_TAGS = {"legal", "medical", "financial", "security"}


@dataclass
class Classification:
    tier: int
    reasons: list[str]


def classify(prompt: str, risk_tags: list[str] | None = None, output_format: str = "text") -> Classification:
    reasons = []
    risk = set(risk_tags or []) & HIGH_RISK_TAGS
    if risk:
        return Classification(3, [f"high-risk tags: {sorted(risk)}"])
    words = len(prompt.split())
    if TIER3_VERBS.search(prompt):
        reasons.append("reasoning verb")
        tier = 3
    elif TIER2_VERBS.search(prompt):
        reasons.append("summarise/classify verb")
        tier = 2
    elif TIER1_VERBS.search(prompt):
        reasons.append("extraction/formatting verb")
        tier = 1
    else:
        reasons.append("no strong signal")
        tier = 2
    if words > 600 and tier < 3:
        tier += 1
        reasons.append(f"long context ({words} words)")
    if output_format == "json" and tier == 2 and words < 120:
        tier = 1
        reasons.append("short structured output")
    return Classification(tier, reasons)
