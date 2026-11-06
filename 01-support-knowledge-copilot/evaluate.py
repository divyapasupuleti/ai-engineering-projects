#!/usr/bin/env python3
"""Run the golden set and compare retrieval strategies. Writes reports/eval_report.md.

    python evaluate.py --strategy all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from answer import answer_question  # noqa: E402
from common.io import read_jsonl  # noqa: E402
from common.stats import mean  # noqa: E402
from ingest import build_index  # noqa: E402
from retrieval import Retriever  # noqa: E402

GOLDEN = ROOT / "data" / "golden.jsonl"
REPORT = ROOT / "reports" / "eval_report.md"


CONFIGS = {
    "dense": ("dense", False),
    "sparse": ("sparse", False),
    "hybrid": ("hybrid", False),
    "hybrid+rerank": ("hybrid", True),
}


def evaluate(name: str, index: dict, golden: list[dict]) -> dict:
    strategy, rerank = CONFIGS[name]
    retriever = Retriever(index, strategy, rerank=rerank)
    answerable = [g for g in golden if g["answerable"]]
    unanswerable = [g for g in golden if not g["answerable"]]
    top1 = recall5 = correct_refusals = false_refusals = 0
    citation_rates, confidences, failures = [], [], []
    for g in golden:
        hits = retriever.search(g["question"])
        docs = [h.chunk["doc"] for h in hits]
        ans = answer_question(g["question"], retriever)
        if g["answerable"]:
            top1 += bool(docs) and docs[0] == g["expected_doc"]
            recall5 += g["expected_doc"] in docs
            false_refusals += ans.refused
            if not ans.refused:
                rate = ans.breakdown.get("citation_support_rate", 0.0)
                citation_rates.append(rate)
                confidences.append(ans.confidence)
            if not docs or docs[0] != g["expected_doc"]:
                failures.append(f"{g['id']} top1={docs[0] if docs else None} expected={g['expected_doc']}")
        else:
            correct_refusals += ans.refused
            if not ans.refused:
                failures.append(f"{g['id']} answered an unanswerable question")
    return {
        "strategy": name,
        "top1_source_accuracy": top1 / len(answerable),
        "source_recall_at_5": recall5 / len(answerable),
        "refusal_accuracy": correct_refusals / max(1, len(unanswerable)),
        "false_refusal_rate": false_refusals / len(answerable),
        "citation_validity": mean(citation_rates),
        "avg_confidence": mean(confidences),
        "failures": failures,
    }


def render(results: list[dict], n: int) -> str:
    cols = ["top1_source_accuracy", "source_recall_at_5", "refusal_accuracy", "false_refusal_rate", "citation_validity", "avg_confidence"]
    lines = [f"# Support Copilot eval report ({n} golden questions)", "", "| Strategy | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for r in results:
        lines.append(f"| {r['strategy']} | " + " | ".join(f"{r[c]:.1%}" if c != "avg_confidence" else f"{r[c]:.2f}" for c in cols) + " |")
    for r in results:
        lines += ["", f"## Failures: {r['strategy']}", *(f"- {f}" for f in r["failures"] or ["none"])]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", choices=["all", *CONFIGS], default="all")
    args = ap.parse_args()
    golden = read_jsonl(GOLDEN)
    index = build_index(ROOT / "data" / "docs")
    strategies = list(CONFIGS) if args.strategy == "all" else [args.strategy]
    results = [evaluate(s, index, golden) for s in strategies]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(render(results, len(golden)), encoding="utf-8")
    for r in results:
        print(
            f"{r['strategy']:>13}: top1={r['top1_source_accuracy']:.1%} recall@5={r['source_recall_at_5']:.1%} "
            f"refusal_acc={r['refusal_accuracy']:.1%} false_refusal={r['false_refusal_rate']:.1%} "
            f"citation_valid={r['citation_validity']:.1%}"
        )
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
