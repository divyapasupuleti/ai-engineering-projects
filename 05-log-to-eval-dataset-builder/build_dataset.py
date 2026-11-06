#!/usr/bin/env python3
"""Run the nightly log -> eval pipeline and print dataset health.

    python generate_logs.py && python build_dataset.py --sample-mode failure_biased --k 400
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.embeddings import embed  # noqa: E402
from common.io import read_jsonl, write_jsonl  # noqa: E402
from generate_logs import generate  # noqa: E402
from pipeline import auto_label, cluster_labels, dedupe, kmeans, redact, sample, to_row, value_score  # noqa: E402

AUTO_APPROVE = 0.85
N_CLUSTERS = 8


def cluster_by_feature(logs: list[dict]) -> list[int]:
    """Cluster within each feature (k proportional to its share) so clusters never mix products."""
    assign = [0] * len(logs)
    next_id = 0
    by_feature: dict[str, list[int]] = {}
    for i, l in enumerate(logs):
        by_feature.setdefault(l["feature"], []).append(i)
    for idxs in by_feature.values():
        k = max(2, round(N_CLUSTERS * len(idxs) / len(logs)))
        local = kmeans([embed(logs[i]["prompt"]) for i in idxs], min(k, len(idxs)))
        for i, a in zip(idxs, local):
            assign[i] = next_id + a
        next_id += k
    return assign


def simulated_review(cases, seed: int = 9) -> list[dict]:
    """Stand-in for the Streamlit review queue: approve / edit / reject with recorded reasons."""
    rng = random.Random(seed)
    edits = []
    for c in cases:
        if c.status != "draft":
            continue
        r = rng.random()
        if r < 0.72:
            c.status = "approved"
        elif r < 0.92:
            c.status = "approved"
            old = list(c.rubric)
            c.rubric = c.rubric + ["cites the relevant help-center page"]
            edits.append({"case": c.id, "field": "rubric", "before": old, "after": c.rubric, "reason": "reviewer added grounding criterion"})
        else:
            c.status = "rejected"
            edits.append({"case": c.id, "field": "status", "before": "draft", "after": "rejected", "reason": "ambiguous expected behaviour"})
    return edits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample-mode", choices=["random", "failure_biased", "diversity"], default="failure_biased")
    ap.add_argument("--k", type=int, default=400)
    args = ap.parse_args()

    logs_path = ROOT / "data" / "logs.jsonl"
    logs = read_jsonl(logs_path) if logs_path.exists() else generate(1000)
    redacted = [redact(l) for l in logs]
    n_redacted = sum(l["redaction"]["redacted"] for l in redacted)

    picked = sample(redacted, args.sample_mode, args.k)
    fail_share = sum(l["user_feedback"] == "down" or l["retry_count"] > 0 or bool(l["error_status"]) for l in picked) / len(picked)

    assign = cluster_by_feature(picked)
    labels = cluster_labels(picked, assign)
    sizes = Counter(assign)
    covered: Counter[int] = Counter()
    scored = []
    for log, c in sorted(zip(picked, assign), key=lambda x: -value_score(x[0], sizes[x[1]], Counter(), x[1])):
        scored.append((value_score(log, sizes[c], covered, c), log, c))
        covered[c] += 1
    candidates = [auto_label(log, labels[c]) for s, log, c in scored if s >= 0.2]

    existing = read_jsonl(ROOT / "data" / "existing_evals.jsonl")
    kept, rejected = dedupe(candidates, existing)
    for c in kept:
        c.status = "approved" if c.label_confidence >= AUTO_APPROVE else "draft"
    auto_approved = sum(c.status == "approved" for c in kept)
    to_review = [c for c in kept if c.status == "draft"]
    edits = simulated_review(kept)
    reviewed_ok = sum(1 for c in to_review if c.status == "approved")

    approved = [c for c in kept if c.status == "approved"]
    write_jsonl(ROOT / "evals" / "eval_set.jsonl", [to_row(c) for c in approved])
    write_jsonl(ROOT / "evals" / "review_queue.jsonl", [to_row(c) for c in kept if c.status != "approved"])
    write_jsonl(ROOT / "evals" / "reviewer_edits.jsonl", edits)
    write_jsonl(ROOT / "evals" / "rejected.jsonl", [{"id": i, "reason": r} for i, r in rejected])

    unedited = reviewed_ok - sum(1 for e in edits if e["field"] == "rubric")
    print(f"Logs: {len(logs)} · redacted: {n_redacted} · sample mode: {args.sample_mode} ({len(picked)} picked, {fail_share:.0%} failure signals)")
    print(f"Clusters ({N_CLUSTERS}):")
    for c, label in labels.items():
        print(f"  [{sizes[c]:>3}] {label}")
    print(f"Candidates: {len(candidates)} · near-duplicates rejected: {len(rejected)} · kept: {len(kept)}")
    print(f"Auto-approved (confidence >= {AUTO_APPROVE}): {auto_approved} · sent to review: {len(to_review)}")
    print(f"Review: {reviewed_ok} approved ({unedited} unedited, {reviewed_ok - unedited} edited), {len(to_review) - reviewed_ok} rejected")
    print(f"Auto-label acceptance after review: {unedited / max(1, len(to_review)):.0%}")
    types = Counter(c.eval_type for c in approved)
    diff = Counter(c.difficulty for c in approved)
    feats = Counter(c.feature for c in approved)
    print(f"Approved eval set: {len(approved)} cases -> evals/eval_set.jsonl")
    print(f"  by type: {dict(types)}")
    print(f"  by feature: {dict(feats)}")
    print(f"  by difficulty: {dict(diff)}")


if __name__ == "__main__":
    main()
