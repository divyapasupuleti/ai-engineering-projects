"""Rubric-driven judges. Simulated LLM judges score observable features with model-specific bias and noise."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

ABSOLUTES = re.compile(r"\b(guaranteed|always|never|unlimited|permanently|every case)\b", re.I)
FILLER_RE = re.compile(r"thank you so much for reaching out", re.I)
CITATION_RE = re.compile(r"\[kb:[^\]]+\]")


def load_rubric(path: Path) -> dict:
    return json.loads(path.read_text())


@dataclass
class Judgement:
    score: int
    criteria: dict[str, float]
    rationale: str
    judge: str
    cost: float


@dataclass
class RubricJudge:
    name: str
    noise: float          # probability of a +/-1 slip, deterministic per (judge, item)
    leniency: float       # added to the raw score; >0 = lenient
    cost_per_call: float

    def _slip(self, key: str) -> int:
        h = int(hashlib.sha256(f"{self.name}:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if h < self.noise / 2:
            return -1
        if h < self.noise:
            return 1
        return 0

    def judge(self, rubric: dict, item: dict, output: str, key: str) -> Judgement:
        text = output.lower()
        facts = item["key_facts"]
        crit = {
            "correctness": sum(f in text for f in facts) / len(facts),
            "grounding": 1.0 if CITATION_RE.search(output) else 0.0,
            "no_unsupported_claims": 0.0 if ABSOLUTES.search(output) else 1.0,
            "concise": 0.0 if FILLER_RE.search(output) else 1.0,
        }
        weighted = sum(c["weight"] * crit[c["name"]] for c in rubric["criteria"])
        raw = 1 + 4 * weighted + self.leniency
        score = max(rubric["scale"][0], min(rubric["scale"][1], round(raw) + self._slip(key)))
        weakest = min(crit, key=crit.get)
        return Judgement(score, {k: round(v, 2) for k, v in crit.items()},
                         f"weakest criterion: {weakest} ({crit[weakest]:.2f})", self.name, self.cost_per_call)


JUDGES = {
    "judge-mini": RubricJudge("judge-mini", noise=0.30, leniency=0.45, cost_per_call=0.0004),
    "judge-large": RubricJudge("judge-large", noise=0.10, leniency=0.1, cost_per_call=0.006),
}
