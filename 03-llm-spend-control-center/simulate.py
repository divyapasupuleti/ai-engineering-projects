#!/usr/bin/env python3
"""Send a seeded mixed workload through the gateway and write the cost dashboard report.

    python simulate.py --requests 1000
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.pricing import cost_usd  # noqa: E402
from common.stats import mean, percentile  # noqa: E402
from gateway import BudgetExceeded, GatewayRequest, SpendGateway  # noqa: E402

WORKLOAD = [
    ("support", "ticket_tagging", "Classify this support ticket into billing, bug or how-to: {x}", [], "json", 2, 0.25),
    ("support", "reply_draft", "Summarise the customer thread and rewrite a polite reply: {x}", [], "text", 2, 0.15),
    ("support", "field_extract", "Extract the order id and email from: {x}", [], "json", 1, 0.15),
    ("sales", "crm_cleanup", "Format these contact notes as a table: {x}", [], "text", 1, 0.12),
    ("sales", "deal_analysis", "Analyze why this deal stalled and plan next steps: {x}", [], "text", 3, 0.08),
    ("legal", "contract_review", "Review this clause for liability exposure: {x}", ["legal"], "text", 3, 0.07),
    ("engineering", "log_triage", "Diagnose the root cause from these logs: {x}", [], "text", 3, 0.08),
    ("engineering", "commit_summary", "Summarise these commits for release notes: {x}", [], "text", 2, 0.10),
]
FILLER = "customer acme order 4411 latency spike since tuesday invoice mismatch export failing".split()
DAYS = ["2026-11-01", "2026-11-02", "2026-11-03"]


def make_requests(n: int, seed: int = 3) -> list[GatewayRequest]:
    rng = random.Random(seed)
    weights = [w[-1] for w in WORKLOAD]
    out = []
    for i in range(n):
        team, feature, tmpl, tags, fmt, difficulty, _ = rng.choices(WORKLOAD, weights=weights)[0]
        body = " ".join(rng.choices(FILLER, k=rng.randint(15, 90)))
        if rng.random() < 0.08:
            difficulty = min(3, difficulty + 1)
        priority = rng.choices(["low", "normal", "high"], weights=[3, 6, 1])[0]
        out.append(GatewayRequest(team, feature, tmpl.format(x=body), priority, tags, fmt, difficulty=difficulty, day=DAYS[i * len(DAYS) // n]))
    return out


def report(gw: SpendGateway, n: int, blocked: int) -> str:
    rows = gw.db.execute("SELECT team, feature, model, input_tokens, output_tokens, latency_ms, cost_usd, escalated, over_budget, tier FROM requests WHERE status='ok'").fetchall()
    strong = gw.routing["strong_model"]
    actual = sum(r[6] for r in rows)
    all_strong = sum(cost_usd(strong, r[3], r[4]) for r in rows)
    by_team, by_feature, by_model_lat = defaultdict(float), defaultdict(float), defaultdict(list)
    models = defaultdict(int)
    for r in rows:
        by_team[r[0]] += r[6]
        by_feature[r[1]] += r[6]
        by_model_lat[r[2]].append(r[5])
        models[r[2]] += 1
    ver = gw.db.execute("SELECT COUNT(*), COALESCE(SUM(passed),0) FROM verifications").fetchone()
    misses = gw.db.execute("SELECT model, reason FROM verifications WHERE passed=0 LIMIT 5").fetchall()
    alerts = gw.db.execute("SELECT day, team, level, message FROM alerts ORDER BY id").fetchall()
    escalations = sum(r[7] for r in rows)
    overrides = sum(r[8] for r in rows)
    savings = 1 - actual / all_strong if all_strong else 0
    days = len(DAYS)
    lines = [
        f"# LLM spend report ({n} simulated requests over {days} days)",
        "",
        f"- Served: {len(rows)} · blocked by budget: {blocked} · budget overrides: {overrides}",
        f"- Actual spend: ${actual:.4f} · all-{strong} counterfactual: ${all_strong:.4f} · **savings {savings:.1%}**",
        f"- Monthly projection at this rate: ${actual / days * 30:.2f}",
        f"- Verifier pass rate: {ver[1] / ver[0]:.1%} on {ver[0]} sampled cheap-model responses" if ver[0] else "- Verifier: no samples",
        f"- Escalation rate: {escalations / len(rows):.1%}",
        "",
        "## Spend by team",
        "| Team | Spend | Daily budget |",
        "|---|---|---|",
        *[f"| {t} | ${s:.4f} | ${gw.budgets[t]['daily_usd']:.2f} |" for t, s in sorted(by_team.items(), key=lambda x: -x[1])],
        "",
        "## Spend by feature",
        "| Feature | Spend |",
        "|---|---|",
        *[f"| {f} | ${s:.4f} |" for f, s in sorted(by_feature.items(), key=lambda x: -x[1])],
        "",
        "## Model mix and latency",
        "| Model | Requests | p50 ms | p95 ms |",
        "|---|---|---|---|",
        *[f"| {m} | {models[m]} | {percentile(v, 50):.0f} | {percentile(v, 95):.0f} |" for m, v in sorted(by_model_lat.items())],
        "",
        "## Routing misses (sample)",
        *([f"- {m}: {reason}" for m, reason in misses] or ["- none"]),
        "",
        "## Budget alerts",
        *([f"- {d} [{lvl}] {msg}" for d, t, lvl, msg in alerts] or ["- none"]),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--requests", type=int, default=1000)
    ap.add_argument("--db", default=str(ROOT / "reports" / "spend.db"))
    args = ap.parse_args()
    Path(args.db).parent.mkdir(exist_ok=True)
    Path(args.db).unlink(missing_ok=True)
    gw = SpendGateway(args.db)
    blocked = 0
    for req in make_requests(args.requests):
        try:
            gw.handle(req)
        except BudgetExceeded:
            blocked += 1
    gw.db.commit()
    text = report(gw, args.requests, blocked)
    (ROOT / "reports" / "spend_report.md").write_text(text, encoding="utf-8")
    print("\n".join(text.splitlines()[:9]))
    print("...")
    print("Full report: reports/spend_report.md  ·  audit trail: reports/spend.db")


if __name__ == "__main__":
    main()
