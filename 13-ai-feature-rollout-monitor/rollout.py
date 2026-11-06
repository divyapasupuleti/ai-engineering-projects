"""Rollout controller: stages, guardrails, segment checks, decisions and an append-only audit log."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from common.stats import percentile
from stats_tests import worse_proportion

STAGES = [1, 5, 25, 50, 100]


@dataclass
class Guardrails:
    max_safety_rate: float = 0.002          # absolute: treatment above this -> rollback
    min_safety_events: int = 2
    quality_alpha: float = 0.01             # significance for 'treatment worse'
    quality_min_diff: float = 0.02          # and at least 2pp worse to act
    latency_p95_max_ratio: float = 1.2
    cost_max_ratio: float = 1.3
    error_max_diff: float = 0.01
    min_treatment_samples: int = 400
    segments: tuple[str, ...] = ("locale", "plan")


@dataclass
class Observation:
    user_id: str
    arm: str  # control | treatment
    bad_quality: bool
    thumbs_down: bool
    latency_ms: float
    cost: float
    error: bool
    safety_violation: bool
    segment: dict[str, str]


@dataclass
class Decision:
    stage_percent: float
    action: str  # promote | hold | pause | rollback | complete
    reasons: list[str]
    metrics: dict


@dataclass
class RolloutController:
    feature: str
    audit_path: Path
    guardrails: Guardrails = field(default_factory=Guardrails)
    stage_idx: int = 0
    state: str = "running"  # running | paused | rolled_back | complete
    obs: list[Observation] = field(default_factory=list)

    @property
    def percent(self) -> float:
        return 0.0 if self.state == "rolled_back" else STAGES[self.stage_idx]

    def record(self, o: Observation) -> None:
        self.obs.append(o)

    def _audit(self, event: str, **data) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), "feature": self.feature, "event": event,
                                "stage_percent": STAGES[self.stage_idx], "state": self.state, **data}) + "\n")

    def metrics(self, obs: list[Observation]) -> dict:
        out = {}
        for arm in ("control", "treatment"):
            a = [o for o in obs if o.arm == arm]
            n = max(1, len(a))
            out[arm] = {
                "n": len(a), "bad_quality": sum(o.bad_quality for o in a) / n, "thumbs_down": sum(o.thumbs_down for o in a) / n,
                "p95_ms": percentile([o.latency_ms for o in a], 95) if a else 0, "cost": sum(o.cost for o in a) / n,
                "error": sum(o.error for o in a) / n, "safety": sum(o.safety_violation for o in a) / n,
            }
        return out

    def evaluate(self) -> Decision:
        g = self.guardrails
        stage_obs = self.obs
        m = self.metrics(stage_obs)
        c, t = m["control"], m["treatment"]
        reasons: list[str] = []
        safety_events = sum(o.safety_violation for o in stage_obs if o.arm == "treatment")
        if safety_events >= g.min_safety_events and t["safety"] > g.max_safety_rate:
            return self._decide("rollback", [f"{safety_events} safety violations ({t['safety']:.2%} > {g.max_safety_rate:.2%})"], m)
        if t["n"] < g.min_treatment_samples:
            return self._decide("hold", [f"only {t['n']} treatment samples (< {g.min_treatment_samples})"], m)
        for metric in ("bad_quality", "thumbs_down"):
            test = worse_proportion(sum(getattr(o, metric) for o in stage_obs if o.arm == "control"), c["n"],
                                    sum(getattr(o, metric) for o in stage_obs if o.arm == "treatment"), t["n"])
            if test.p_value < g.quality_alpha and test.diff >= g.quality_min_diff:
                reasons.append(f"{metric} +{test.diff:.1%} (p={test.p_value:.4f})")
        for dim in g.segments:
            for value in sorted({o.segment[dim] for o in stage_obs}):
                seg = [o for o in stage_obs if o.segment[dim] == value]
                sc = [o for o in seg if o.arm == "control"]
                st = [o for o in seg if o.arm == "treatment"]
                if len(st) < 100:
                    continue
                test = worse_proportion(sum(o.bad_quality for o in sc), len(sc), sum(o.bad_quality for o in st), len(st))
                if test.p_value < g.quality_alpha / 4 and test.diff >= 2 * g.quality_min_diff:
                    reasons.append(f"segment {dim}={value}: bad_quality +{test.diff:.1%} (p={test.p_value:.4f}, n={len(st)})")
        if c["p95_ms"] and t["p95_ms"] > g.latency_p95_max_ratio * c["p95_ms"]:
            reasons.append(f"p95 latency {t['p95_ms']:.0f} ms vs {c['p95_ms']:.0f} ms (x{t['p95_ms'] / c['p95_ms']:.2f})")
        if c["cost"] and t["cost"] > g.cost_max_ratio * c["cost"]:
            reasons.append(f"cost/request x{t['cost'] / c['cost']:.2f}")
        if t["error"] - c["error"] > g.error_max_diff:
            reasons.append(f"error rate +{t['error'] - c['error']:.1%}")
        if reasons:
            return self._decide("pause", reasons, m)
        if self.stage_idx == len(STAGES) - 1:
            return self._decide("complete", ["all guardrails green at 100%"], m)
        return self._decide("promote", [f"guardrails green with {t['n']} treatment samples"], m)

    def _decide(self, action: str, reasons: list[str], m: dict) -> Decision:
        d = Decision(STAGES[self.stage_idx], action, reasons, m)
        if action == "rollback":
            self.state = "rolled_back"
        elif action == "pause":
            self.state = "paused"
        elif action == "complete":
            self.state = "complete"
        self._audit("decision", action=action, reasons=reasons,
                    metrics={arm: {k: round(v, 5) if isinstance(v, float) else v for k, v in vals.items()} for arm, vals in m.items()})
        if action == "promote":
            self.stage_idx += 1
            self.obs = []
            self._audit("stage_change", to_percent=STAGES[self.stage_idx])
        return d

    def human_resume(self, actor: str, note: str) -> None:
        if self.state != "paused":
            raise ValueError(f"cannot resume from {self.state}")
        self.state = "running"
        self.obs = []
        self._audit("resume", actor=actor, note=note)

    def human_rollback(self, actor: str, note: str) -> None:
        self.state = "rolled_back"
        self._audit("rollback", actor=actor, note=note)
