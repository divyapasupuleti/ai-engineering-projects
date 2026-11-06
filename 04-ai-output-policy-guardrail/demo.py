#!/usr/bin/env python3
"""Run the sample outputs through the guardrail, print decisions, stats, and a policy-version diff.

    python demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.io import read_jsonl  # noqa: E402
from guardrail import CheckRequest, GuardrailService  # noqa: E402

SAMPLES = ROOT / "data" / "samples.jsonl"


def load() -> list[CheckRequest]:
    return [CheckRequest(**row) for row in read_jsonl(SAMPLES)]


def main() -> None:
    reqs = load()
    v2 = GuardrailService(ROOT / "policies" / "policies.v2.json")
    print(f"Policy version {v2.version}: {len(reqs)} outputs\n")
    decisions = []
    for r in reqs:
        d = v2.check(r)
        decisions.append(d)
        shown = (d.final_output or "<withheld>")[:70]
        print(f"[{d.action:<20}] {r.feature:<16} reasons={','.join(d.reason_codes) or '-'}")
        if d.action in ("rewrite",):
            print(f"{'':23}-> {shown}")
    review_id = next(d.decision_id for d in decisions if d.action == "human_review")
    v2.review(review_id, "reviewer@company", "confirmed_block", "refund window contradicts context")
    stats = v2.stats()
    print(f"\nRates: {stats['rates']}")
    print(f"Top violations: {stats['top_violations'][:4]}")
    print(f"Avg guardrail latency: {stats['avg_latency_ms']} ms (deterministic checks first)")

    v1 = GuardrailService(ROOT / "policies" / "policies.v1.json")
    changed = []
    for r, d2 in zip(reqs, decisions):
        d1 = v1.check(r)
        if d1.action != d2.action:
            changed.append((r.feature, d1.action, d2.action))
    print(f"\nPolicy diff v{v1.version} -> v{v2.version}: {len(changed)} of {len(reqs)} historical decisions change")
    for feature, a1, a2 in changed:
        print(f"  {feature:<16} {a1} -> {a2}")


if __name__ == "__main__":
    main()
