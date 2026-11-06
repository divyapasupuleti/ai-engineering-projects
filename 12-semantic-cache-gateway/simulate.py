#!/usr/bin/env python3
"""Replay 2,000 requests through five cache configurations and a threshold sweep.

    python simulate.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from cache import SemanticCache  # noqa: E402
from common.io import write_json, write_jsonl  # noqa: E402
from common.stats import percentile  # noqa: E402
from gateway import CacheGateway  # noqa: E402
from workload import generate  # noqa: E402

THRESHOLD = 0.80
PRICING_CHANGE_AT = 1000


def replay(gw: CacheGateway, reqs, invalidate: bool = True) -> dict:
    sources, wrong, cost, lat = Counter(), [], 0.0, []
    for i, r in enumerate(reqs):
        if invalidate and i == PRICING_CHANGE_AT and gw.cache:
            gw.cache.invalidate_tag("pricing")
        res = gw.handle(r.tenant, r.user, r.prompt, r.answer_id, r.t)
        sources[res.source] += 1
        cost += res.cost
        lat.append(res.latency_ms)
        if res.answer_id != r.answer_id:
            wrong.append({"prompt": r.prompt, "served_for": res.answer_id, "truth": r.answer_id,
                          "source": res.source, "sim": round(res.similarity, 3)})
    n = len(reqs)
    hits = sources["exact"] + sources["semantic"]
    return {"hit_rate": hits / n, "exact": sources["exact"], "semantic": sources["semantic"],
            "upstream": sources["upstream"], "bypass": sources["bypass"], "wrong": len(wrong),
            "wrong_rate_of_hits": len(wrong) / max(1, hits), "cost": cost,
            "p50": percentile(lat, 50), "p95": percentile(lat, 95), "wrong_examples": wrong[:5]}


def main() -> None:
    reqs = generate(2000, pricing_change_at=PRICING_CHANGE_AT)
    configs = {
        "no_cache": (CacheGateway(None), True),
        "exact_only": (CacheGateway(SemanticCache(threshold=THRESHOLD), exact_only=True), True),
        "semantic_unvalidated": (CacheGateway(SemanticCache(threshold=THRESHOLD, validate=False)), True),
        "semantic_no_invalidation": (CacheGateway(SemanticCache(threshold=THRESHOLD)), False),
        "semantic_validated": (CacheGateway(SemanticCache(threshold=THRESHOLD)), True),
    }
    results = {name: replay(gw, reqs, inv) for name, (gw, inv) in configs.items()}
    base = results["no_cache"]["cost"]
    print(f"2,000 requests · 3 tenants · pricing changes at request {PRICING_CHANGE_AT} · threshold {THRESHOLD}\n")
    print(f"{'config':<26}{'hit rate':>9}{'exact':>7}{'semantic':>9}{'bypass':>8}{'wrong':>7}{'cost $':>9}{'saved':>7}{'p50 ms':>8}{'p95 ms':>8}")
    for name, r in results.items():
        print(f"{name:<26}{r['hit_rate']:>9.1%}{r['exact']:>7}{r['semantic']:>9}{r['bypass']:>8}{r['wrong']:>7}"
              f"{r['cost']:>9.3f}{1 - r['cost'] / base:>7.0%}{r['p50']:>8.0f}{r['p95']:>8.0f}")
    for name in ("semantic_unvalidated", "semantic_no_invalidation", "semantic_validated"):
        ex = results[name]["wrong_examples"][:2]
        print(f"\n{name} wrong hits, e.g.:")
        for w in ex:
            print(f"  '{w['prompt']}' got answer for {w['served_for']} (truth {w['truth']}, sim {w['sim']})")

    cache = configs["semantic_validated"][0].cache
    why = Counter(m["why"] for m in cache.near_misses)
    print(f"\nNear-miss log (semantic_validated): {len(cache.near_misses)} entries {dict(why)}")
    for m in [m for m in cache.near_misses if m["why"] != "below threshold"][:2]:
        print(f"  blocked: '{m['prompt']}' vs cached '{m['cached']}' (sim {m['sim']})")

    print("\nThreshold sweep (validated, with invalidation):")
    sweep = {}
    for th in (0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
        r = replay(CacheGateway(SemanticCache(threshold=th)), reqs)
        r_nv = replay(CacheGateway(SemanticCache(threshold=th, validate=False)), reqs)
        sweep[th] = {"hit_rate": r["hit_rate"], "wrong": r["wrong"], "wrong_unvalidated": r_nv["wrong"]}
        print(f"  {th:.2f}: hit rate {r['hit_rate']:.1%}  wrong {r['wrong']:>3}  (without validator: {r_nv['wrong']:>3} wrong)")

    reports = ROOT / "reports"
    write_json(reports / "results.json", {k: {kk: vv for kk, vv in v.items() if kk != "wrong_examples"} for k, v in results.items()} | {"sweep": sweep})
    write_jsonl(reports / "near_misses.jsonl", cache.near_misses)
    print("\nWrote reports/results.json and reports/near_misses.jsonl")


if __name__ == "__main__":
    main()
