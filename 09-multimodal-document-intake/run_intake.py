#!/usr/bin/env python3
"""Process all documents, route them, and score extraction against ground truth.

    python generate_docs.py && python run_intake.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.io import read_jsonl, write_jsonl  # noqa: E402
from generate_docs import generate  # noqa: E402
from intake import process  # noqa: E402


def main() -> None:
    path = ROOT / "data" / "documents.jsonl"
    docs = read_jsonl(path) if path.exists() else generate(80)
    seen: set[str] = set()
    results = [(d, process(d, seen)) for d in docs]

    field_hits: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    routes = Counter()
    by_scenario: dict[str, Counter] = defaultdict(Counter)
    escapes, issues_caught, issues_total, type_ok = [], 0, 0, 0
    for d, ex in results:
        truth = d["truth"]
        type_ok += ex.doc_type == truth["doc_type"]
        correct = ex.doc_type == truth["doc_type"]
        for k, v in truth["fields"].items():
            hit = ex.fields.get(k) == v
            field_hits[k][0] += hit
            field_hits[k][1] += 1
            correct &= hit
        routes[ex.route] += 1
        by_scenario[d["scenario"]][ex.route] += 1
        if "issue" in truth:
            issues_total += 1
            issues_caught += ex.route != "auto_approve"
        if ex.route == "auto_approve" and (not correct or "issue" in truth):
            escapes.append(ex.doc_id)

    n = len(results)
    total_fields = sum(t for _, t in field_hits.values())
    print(f"Documents: {n} · type accuracy {type_ok / n:.0%} · field accuracy "
          f"{sum(h for h, _ in field_hits.values()) / total_fields:.1%} ({total_fields} fields)")
    print(f"Routing: {dict(routes)} · straight-through rate {routes['auto_approve'] / n:.0%}")
    print(f"Auto-approved with an error (escapes): {len(escapes)} {escapes}")
    print(f"Business-rule issues caught: {issues_caught}/{issues_total}")
    vision = sum(ex.used_vision for _, ex in results)
    cost = sum(ex.cost for _, ex in results)
    print(f"Vision fallback: {vision} docs · total cost ${cost:.4f} (${cost / n:.5f}/doc vs "
          f"${0.0135:.4f}/doc if every page used vision)")
    print(f"OCR corrections applied: {sum(len(ex.corrections) for _, ex in results)}")
    print("\nRoute by scenario:")
    for s, c in sorted(by_scenario.items()):
        print(f"  {s:<18} {dict(c)}")
    print("\nSample review items:")
    for d, ex in [r for r in results if r[1].route == "human_review"][:5]:
        print(f"  {ex.doc_id} ({d['scenario']}): {'; '.join(ex.route_reasons)[:110]}")
    print("\nField accuracy:")
    for k, (h, t) in sorted(field_hits.items(), key=lambda kv: kv[1][0] / kv[1][1]):
        print(f"  {k:<15} {h}/{t}")

    out = ROOT / "outputs"
    write_jsonl(out / "approved.jsonl", [asdict(ex) for _, ex in results if ex.route == "auto_approve"])
    write_jsonl(out / "review_queue.jsonl", [asdict(ex) for _, ex in results if ex.route == "human_review"])
    write_jsonl(out / "rejected.jsonl", [asdict(ex) for _, ex in results if ex.route == "reject"])


if __name__ == "__main__":
    main()
