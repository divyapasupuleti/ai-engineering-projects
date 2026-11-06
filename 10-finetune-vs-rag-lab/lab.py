#!/usr/bin/env python3
"""Run both experiments, the learning curve and the cost model, then write the decision memo.

    python lab.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from approaches import FineTuned, KnowledgeFineTuned, KnowledgePromptOnly, KnowledgeRAG, PromptOnly, RetrievalFewShot  # noqa: E402
from common.io import write_json  # noqa: E402
from common.pricing import cost_usd  # noqa: E402
from common.text import count_tokens  # noqa: E402
from make_data import CHANGED_IN_V2, fact_questions, kb, kb_docs, tickets  # noqa: E402

BASE = "gpt-4o-mini"
FT_IN, FT_OUT, FT_TRAIN_PER_1K = 0.0003, 0.0012, 0.003  # hosted fine-tuned mini: 2x inference, plus training
EPOCHS = 3
OUTPUT_TOKENS = 6
PREFILL_MS_PER_TOKEN = 0.05
JARGON = ("nimbus", "gatekeeper", "ledger")


def macro_f1(gold: list[str], pred: list[str]) -> float:
    labels = set(gold)
    f1s = []
    for c in labels:
        tp = sum(g == p == c for g, p in zip(gold, pred))
        fp = sum(p == c and g != c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0)
    return sum(f1s) / len(f1s)


def per_1k_cost(prompt_tokens: int, avg_input: int, fine_tuned: bool) -> float:
    tokens_in = prompt_tokens + avg_input
    if fine_tuned:
        return 1000 * (tokens_in / 1000 * FT_IN + OUTPUT_TOKENS / 1000 * FT_OUT)
    return 1000 * cost_usd(BASE, tokens_in, OUTPUT_TOKENS)


def latency(prompt_tokens: int) -> float:
    return 350 + 8 * OUTPUT_TOKENS + PREFILL_MS_PER_TOKEN * prompt_tokens


def task_a() -> dict:
    train, test = tickets(400, seed=1), tickets(300, seed=2, noise=0.0, include_holdout=True)
    avg_in = round(sum(count_tokens(t) for t, _ in test) / len(test))
    gold = [y for _, y in test]
    jargon_idx = [i for i, (t, _) in enumerate(test) if any(j in t.lower() for j in JARGON)]
    models = {"prompt_only": PromptOnly(), "rag_few_shot": RetrievalFewShot(train), "fine_tuned": FineTuned(train)}
    rows = {}
    for name, m in models.items():
        pred = [m.predict(t) for t, _ in test]
        acc = sum(p == g for p, g in zip(pred, gold)) / len(gold)
        jacc = sum(pred[i] == gold[i] for i in jargon_idx) / len(jargon_idx)
        rows[name] = {
            "accuracy": round(acc, 3), "macro_f1": round(macro_f1(gold, pred), 3), "jargon_accuracy": round(jacc, 3),
            "prompt_tokens": m.prompt_tokens, "cost_per_1k": round(per_1k_cost(m.prompt_tokens, avg_in, name == "fine_tuned"), 4),
            "latency_ms": round(latency(m.prompt_tokens + avg_in)),
        }
    train_tokens = sum(count_tokens(t) + 4 for t, _ in train)
    rows["fine_tuned"]["training_cost"] = round(train_tokens / 1000 * FT_TRAIN_PER_1K * EPOCHS, 4)
    curve = {}
    for n in (25, 50, 100, 200, 400):
        sub = train[:n]
        curve[n] = {name: round(sum(m.predict(t) == y for t, y in test) / len(test), 3)
                    for name, m in (("rag_few_shot", RetrievalFewShot(sub)), ("fine_tuned", FineTuned(sub)))}
    return {"rows": rows, "curve": curve, "n_test": len(test), "n_jargon": len(jargon_idx)}


def task_b() -> dict:
    train_q, test_q = fact_questions(seed=3), fact_questions(seed=4)
    v1, v2 = kb(1), kb(2)
    systems_before = {"prompt_only": KnowledgePromptOnly(), "rag": KnowledgeRAG(kb_docs(1)),
                      "fine_tuned": KnowledgeFineTuned(train_q, v1)}
    systems_after = {"prompt_only": KnowledgePromptOnly(), "rag": KnowledgeRAG(kb_docs(2)),
                     "fine_tuned": systems_before["fine_tuned"]}
    out = {}
    for name in systems_before:
        before = sum(systems_before[name].answer(q) == v1[k] for q, k in test_q) / len(test_q)
        after = sum(systems_after[name].answer(q) == v2[k] for q, k in test_q) / len(test_q)
        changed = [(q, k) for q, k in test_q if k in CHANGED_IN_V2]
        on_changed = sum(systems_after[name].answer(q) == v2[k] for q, k in changed) / len(changed)
        out[name] = {"accuracy_v1": round(before, 3), "accuracy_after_update": round(after, 3),
                     "accuracy_on_changed_facts": round(on_changed, 3)}
    out["update_cost"] = {"rag": "re-embed 4 docs (seconds, ~$0.0001)", "fine_tuned": "new training run + eval + deploy (hours)"}
    return out


def main() -> None:
    a, b = task_a(), task_b()
    rows = a["rows"]
    print(f"Task A - ticket routing with company jargon ({a['n_test']} test tickets, {a['n_jargon']} with jargon)")
    print(f"  {'approach':<14}{'acc':>7}{'macroF1':>9}{'jargon':>8}{'prompt tok':>12}{'$/1k req':>10}{'latency':>9}")
    for name, r in rows.items():
        print(f"  {name:<14}{r['accuracy']:>7.1%}{r['macro_f1']:>9.3f}{r['jargon_accuracy']:>8.1%}"
              f"{r['prompt_tokens']:>12}{r['cost_per_1k']:>10.4f}{r['latency_ms']:>8}ms")
    print(f"  fine-tune training cost: ${rows['fine_tuned']['training_cost']} (400 examples x {EPOCHS} epochs)")
    print("  learning curve (accuracy by # labelled examples):")
    for n, accs in a["curve"].items():
        print(f"    n={n:<4} rag={accs['rag_few_shot']:.1%}  fine_tuned={accs['fine_tuned']:.1%}")
    saving = rows["rag_few_shot"]["cost_per_1k"] - rows["fine_tuned"]["cost_per_1k"]
    breakeven = rows["fine_tuned"]["training_cost"] / saving * 1000 if saving > 0 else float("inf")
    print(f"  fine-tune pays back its training cost after ~{breakeven:,.0f} requests vs RAG few-shot")

    print("\nTask B - product facts, 4 of 10 facts change after training")
    print(f"  {'approach':<14}{'before':>8}{'after update':>14}{'changed facts':>15}")
    for name in ("prompt_only", "rag", "fine_tuned"):
        r = b[name]
        print(f"  {name:<14}{r['accuracy_v1']:>8.0%}{r['accuracy_after_update']:>14.0%}{r['accuracy_on_changed_facts']:>15.0%}")
    print(f"  update cost: RAG = {b['update_cost']['rag']}; fine-tune = {b['update_cost']['fine_tuned']}")

    best_a = max(rows, key=lambda k: rows[k]["accuracy"])
    print(f"\nDecision: Task A -> {best_a.replace('_', ' ')} (learns jargon, shortest prompt); "
          f"Task B -> RAG (facts change; fine-tune was {b['fine_tuned']['accuracy_on_changed_facts']:.0%} on changed facts).")
    print("Hybrid recommendation: fine-tune for routing/format/tone, RAG for anything factual or fast-changing.")

    reports = ROOT / "reports"
    write_json(reports / "results.json", {"task_a": a, "task_b": b, "breakeven_requests": round(breakeven)})
    memo = [
        "# Decision memo: fine-tune vs RAG", "",
        "## Task A: ticket routing (behaviour, company jargon)", "",
        "| approach | accuracy | macro-F1 | jargon acc | prompt tokens | $/1k requests |", "|---|---|---|---|---|---|",
        *[f"| {n} | {r['accuracy']:.1%} | {r['macro_f1']} | {r['jargon_accuracy']:.1%} | {r['prompt_tokens']} | {r['cost_per_1k']} |" for n, r in rows.items()],
        "", f"Fine-tune training cost ${rows['fine_tuned']['training_cost']}; pays back after ~{breakeven:,.0f} requests.", "",
        "## Task B: product facts that change", "",
        "| approach | before update | after update | on changed facts |", "|---|---|---|---|",
        *[f"| {n} | {b[n]['accuracy_v1']:.0%} | {b[n]['accuracy_after_update']:.0%} | {b[n]['accuracy_on_changed_facts']:.0%} |" for n in ("prompt_only", "rag", "fine_tuned")],
        "", "## Recommendation", "",
        f"- Routing/format/tone with stable labels and high volume: **{best_a.replace('_', ' ')}**.",
        "- Facts, policies and prices: **RAG**; a fine-tune silently serves stale facts until retrained.",
        "- Start with prompt-only + RAG; fine-tune when you have a few hundred labelled examples, stable labels and volume above the break-even point.",
    ]
    (reports / "decision_memo.md").write_text("\n".join(memo) + "\n")
    print("Wrote reports/decision_memo.md and reports/results.json")


if __name__ == "__main__":
    main()
