"""Guardrail service: run policies over an LLM output and approve, warn, rewrite, block, or route to review."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.io import read_json  # noqa: E402
from detectors import (  # noqa: E402
    Finding,
    detect_keywords,
    detect_pii,
    detect_schema,
    judge_unsupported_claims,
    redact,
    repair_json,
    soften,
)

ACTIONS = ["approve", "approve_with_warning", "rewrite", "human_review", "block"]
AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, ts REAL, feature TEXT, policy_version TEXT, input_hash TEXT, output_hash TEXT,
  action TEXT, findings TEXT, latency_ms REAL, final_output TEXT, reviewer TEXT, review_note TEXT
);
"""


@dataclass
class CheckRequest:
    feature: str
    prompt: str
    output: str
    context: str = ""
    expects_json: bool = False
    allowed_pii: list[str] = field(default_factory=list)
    high_risk: bool = False


@dataclass
class Decision:
    action: str
    final_output: str | None
    findings: list[Finding]
    reason_codes: list[str]
    policy_version: str
    latency_ms: float
    decision_id: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["findings"] = [asdict(f) for f in self.findings]
        return d


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class GuardrailService:
    def __init__(self, policy_file: Path = ROOT / "policies" / "policies.v2.json", db_path: str = ":memory:") -> None:
        cfg = read_json(policy_file)
        self.version = cfg["version"]
        self.policies = cfg["policies"]
        self.db = sqlite3.connect(db_path)
        self.db.executescript(AUDIT_SCHEMA)

    def findings(self, req: CheckRequest) -> list[Finding]:
        out: list[Finding] = []
        for p in self.policies:
            det = p["detector"]
            if det == "schema":
                out += detect_schema(req.output, req.expects_json, p)
            elif det == "pii":
                out += detect_pii(req.output, p, set(req.allowed_pii))
            elif det in ("keywords", "overconfidence", "brand"):
                out += detect_keywords(req.output, p)
        judge_policy = next((p for p in self.policies if p["detector"] == "judge"), None)
        if judge_policy and req.context:
            lenient = judge_unsupported_claims(req.output, req.context, judge_policy)
            if req.high_risk:
                strict = judge_unsupported_claims(req.output, req.context, judge_policy, strict=True)
                if bool(lenient) != bool(strict):
                    for f in strict or lenient:
                        f.detail += " (judges disagree)"
                out += strict or lenient
            else:
                out += lenient
        return out

    def check(self, req: CheckRequest) -> Decision:
        start = time.perf_counter()
        found = self.findings(req)
        action = max((f.action for f in found), key=ACTIONS.index, default="approve")
        final: str | None = req.output
        if action == "rewrite":
            final = redact(req.output, found)
            if any(f.policy_id == "overconfident_advice" for f in found):
                final = soften(final)
            if any(f.policy_id == "schema_mismatch" for f in found):
                repaired = repair_json(final)
                if repaired is None:
                    action, final = "human_review", None
                else:
                    final = repaired
        elif action in ("block", "human_review"):
            final = None
        reasons = sorted({f.policy_id for f in found})
        latency = (time.perf_counter() - start) * 1000
        cur = self.db.execute(
            "INSERT INTO decisions(ts, feature, policy_version, input_hash, output_hash, action, findings, latency_ms, final_output) VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), req.feature, self.version, _hash(req.prompt), _hash(req.output), action,
             json.dumps([asdict(f) for f in found]), latency, final),
        )
        return Decision(action, final, found, reasons, self.version, round(latency, 3), cur.lastrowid)

    def review(self, decision_id: int, reviewer: str, verdict: str, note: str) -> None:
        """Human reviewer approves, overrides a false positive, or confirms a block."""
        self.db.execute(
            "UPDATE decisions SET action=?, reviewer=?, review_note=? WHERE id=?",
            (f"reviewed_{verdict}", reviewer, note, decision_id),
        )

    def stats(self) -> dict:
        rows = self.db.execute("SELECT action, findings, latency_ms FROM decisions").fetchall()
        n = len(rows) or 1
        counts: dict[str, int] = {}
        violations: dict[str, int] = {}
        for action, findings, _ in rows:
            counts[action] = counts.get(action, 0) + 1
            for f in json.loads(findings):
                violations[f["policy_id"]] = violations.get(f["policy_id"], 0) + 1
        return {
            "decisions": len(rows),
            "rates": {a: round(c / n, 3) for a, c in sorted(counts.items())},
            "top_violations": sorted(violations.items(), key=lambda x: -x[1]),
            "avg_latency_ms": round(sum(r[2] for r in rows) / n, 3),
        }
