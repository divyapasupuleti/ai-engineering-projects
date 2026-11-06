#!/usr/bin/env python3
"""Run four rollout scenarios hour by hour and print each controller decision.

    python simulate.py
    python simulate.py --scenario segment_regression
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from flags import in_treatment  # noqa: E402
from rollout import STAGES, Observation, RolloutController  # noqa: E402
from stats_tests import min_samples_per_arm  # noqa: E402

FEATURE = "support-answer-v2"
REQUESTS_PER_HOUR = 4000
MAX_HOURS = 72
BASE = {"bad_quality": 0.08, "thumbs_down": 0.05, "latency": 1200, "cost": 0.0040, "error": 0.01, "safety": 0.0003}
SCENARIOS = {
    "healthy_candidate": {"bad_quality": 0.065, "latency": 1100, "cost": 0.0036},
    "segment_regression": {"bad_quality": 0.066, "segment_bad": ("locale", "de", 0.21)},
    "safety_incident": {"safety": 0.012},
    "latency_regression": {"latency": 1750, "bad_quality": 0.07},
}


def make_users(n: int, rng: random.Random) -> list[tuple[str, dict]]:
    return [(f"u{i:05d}", {"locale": rng.choices(["en", "de", "fr"], [0.7, 0.15, 0.15])[0],
                           "plan": rng.choices(["free", "pro", "enterprise"], [0.6, 0.3, 0.1])[0]}) for i in range(n)]


def observe(user: str, seg: dict, arm: str, scenario: dict, rng: random.Random) -> Observation:
    p = dict(BASE)
    if arm == "treatment":
        p.update({k: v for k, v in scenario.items() if k in BASE})
        if "segment_bad" in scenario:
            dim, val, rate = scenario["segment_bad"]
            if seg[dim] == val:
                p["bad_quality"] = rate
    bad = rng.random() < p["bad_quality"]
    return Observation(user, arm, bad, rng.random() < (p["thumbs_down"] + (0.25 if bad else 0)) / 1.25,
                       rng.lognormvariate(0, 0.35) * p["latency"], p["cost"] * rng.uniform(0.7, 1.3),
                       rng.random() < p["error"], rng.random() < p["safety"], seg)


def run(name: str, scenario: dict, seed: int = 4) -> RolloutController:
    rng = random.Random(seed)
    users = make_users(50_000, rng)
    audit = ROOT / "audit" / f"{name}.jsonl"
    audit.unlink(missing_ok=True)
    ctl = RolloutController(FEATURE, audit)
    print(f"\n=== {name} ===")
    for hour in range(1, MAX_HOURS + 1):
        for _ in range(REQUESTS_PER_HOUR):
            uid, seg = rng.choice(users)
            arm = "treatment" if in_treatment(uid, FEATURE, ctl.percent) else "control"
            ctl.record(observe(uid, seg, arm, scenario, rng))
        stage = ctl.percent
        d = ctl.evaluate()
        if d.action != "hold":
            t = d.metrics["treatment"]
            print(f"  hour {hour:>2} @ {stage:>3}%: {d.action.upper():<8} {'; '.join(d.reasons)}"
                  f"  [treatment n={t['n']}, bad={t['bad_quality']:.1%}, p95={t['p95_ms']:.0f} ms]")
        if ctl.state == "paused":
            if name == "latency_regression":
                ctl.human_rollback("oncall@company", "latency SLO breach confirmed; rolling back")
                print(f"  hour {hour:>2}: human rollback by on-call -> 0%")
            else:
                ctl.human_rollback("ml-lead@company", "German answers regressed; fix prompt localisation before retry")
                print(f"  hour {hour:>2}: human reviewed segment breakdown -> rollback to 0%")
            break
        if ctl.state in ("rolled_back", "complete"):
            break
    exposed = sum(1 for uid, _ in users if in_treatment(uid, FEATURE, STAGES[ctl.stage_idx]))
    print(f"  final state: {ctl.state} · max users exposed: {exposed:,} of {len(users):,} · audit -> audit/{name}.jsonl")
    return ctl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=list(SCENARIOS))
    args = ap.parse_args()
    n = min_samples_per_arm(BASE["bad_quality"], 0.02)
    print(f"Power check: detecting a +2pp rise in an 8% bad-answer rate needs ~{n:,} samples per arm "
          f"(guardrail minimum per stage: 400; small stages only catch large regressions).")
    for name, sc in SCENARIOS.items():
        if args.scenario in (None, name):
            run(name, sc)


if __name__ == "__main__":
    main()
