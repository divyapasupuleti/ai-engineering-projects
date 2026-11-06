#!/usr/bin/env python3
"""Prompt release safety gate: baseline vs candidate on the golden set, thresholds, report, exit code.

    python gate.py --candidate prompts/crm_summary.candidate.json        # demo: BLOCK
    python gate.py --candidate prompts/crm_summary.candidate_good.json   # demo: PASS
    python gate.py --changed-files prompts/crm_summary.prod.json --candidate ...
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.io import read_json, read_jsonl  # noqa: E402
from common.stats import mean, percentile  # noqa: E402
from feature import CONTACT_RE, run_prompt  # noqa: E402
from schema import parse_output  # noqa: E402

GOLDEN = ROOT / "evals" / "golden.jsonl"
REPORTS = ROOT / "reports"


@dataclass
class CaseResult:
    id: str
    risk_area: str
    schema_valid: bool
    fields_correct: int
    fields_total: int
    safety_issue: bool
    latency_ms: float
    cost_usd: float
    output: str
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.schema_valid and not self.safety_issue and self.fields_correct == self.fields_total


def score_case(prompt: dict, case: dict) -> CaseResult:
    call = run_prompt(prompt, case["note"])
    parsed, errors = parse_output(call.raw_output)
    exp = case["expected"]
    correct = 0
    if parsed:
        correct += parsed.sentiment == exp["sentiment"]
        correct += parsed.urgency == exp["urgency"]
        correct += parsed.next_action == exp["next_action"]
        correct += all(k in parsed.summary.lower() for k in exp["summary_keywords"])
    leaked = bool(CONTACT_RE.search(call.raw_output)) and case["contains_contact"]
    if leaked:
        errors.append("contact details leaked into output")
    return CaseResult(case["id"], case["risk_area"], parsed is not None, correct, 4, leaked, call.latency_ms, call.cost_usd, call.raw_output, errors)


def summarise(results: list[CaseResult]) -> dict:
    n = len(results)
    return {
        "cases": n,
        "pass_rate": sum(r.passed for r in results) / n,
        "schema_validity": sum(r.schema_valid for r in results) / n,
        "field_accuracy": sum(r.fields_correct for r in results) / sum(r.fields_total for r in results),
        "safety_failures": sum(r.safety_issue for r in results),
        "avg_cost_usd": mean([r.cost_usd for r in results]),
        "p95_latency_ms": percentile([r.latency_ms for r in results], 95),
    }


def decide(base: dict, cand: dict, cfg: dict) -> tuple[str, list[str]]:
    reasons_block, reasons_warn = [], []
    checks = [
        ("schema_validity_drop", base["schema_validity"] - cand["schema_validity"], "schema validity dropped {:.1%}"),
        ("field_accuracy_drop", base["field_accuracy"] - cand["field_accuracy"], "field accuracy dropped {:.1%}"),
        ("avg_cost_increase_pct", (cand["avg_cost_usd"] / base["avg_cost_usd"] - 1) * 100 if base["avg_cost_usd"] else 0, "average cost up {:.0f}%"),
        ("p95_latency_increase_pct", (cand["p95_latency_ms"] / base["p95_latency_ms"] - 1) * 100, "p95 latency up {:.0f}%"),
    ]
    for key, delta, msg in checks:
        if delta > cfg["block"][key]:
            reasons_block.append(msg.format(delta))
        elif delta > cfg["warn"].get(key, float("inf")):
            reasons_warn.append(msg.format(delta))
    extra_safety = cand["safety_failures"] - base["safety_failures"]
    if extra_safety > cfg["block"]["safety_failures_increase"]:
        reasons_block.append(f"{extra_safety} new safety failures (contact leakage)")
    if reasons_block:
        return "BLOCK", reasons_block + reasons_warn
    if reasons_warn:
        return "WARN", reasons_warn
    return "PASS", ["no regressions beyond thresholds"]


def diff_cases(base: list[CaseResult], cand: list[CaseResult]) -> tuple[list[tuple[CaseResult, CaseResult]], list[CaseResult]]:
    regressed = [(b, c) for b, c in zip(base, cand) if b.passed and not c.passed]
    improved = [c for b, c in zip(base, cand) if not b.passed and c.passed]
    return regressed, improved


def by_risk(results: list[CaseResult]) -> dict[str, float]:
    areas: dict[str, list[bool]] = {}
    for r in results:
        areas.setdefault(r.risk_area, []).append(r.passed)
    return {a: sum(v) / len(v) for a, v in sorted(areas.items())}


def render_markdown(bp: dict, cp: dict, base: dict, cand: dict, decision: str, reasons: list[str], regressed, improved, risk_b, risk_c) -> str:
    rows = [
        ("pass_rate", f"{base['pass_rate']:.1%}", f"{cand['pass_rate']:.1%}"),
        ("schema_validity", f"{base['schema_validity']:.1%}", f"{cand['schema_validity']:.1%}"),
        ("field_accuracy", f"{base['field_accuracy']:.1%}", f"{cand['field_accuracy']:.1%}"),
        ("safety_failures", base["safety_failures"], cand["safety_failures"]),
        ("avg_cost_usd", f"{base['avg_cost_usd']:.6f}", f"{cand['avg_cost_usd']:.6f}"),
        ("p95_latency_ms", f"{base['p95_latency_ms']:.0f}", f"{cand['p95_latency_ms']:.0f}"),
    ]
    out = [
        f"# Prompt release report: {cp['id']} {bp['version']} -> {cp['version']}",
        "",
        f"**Decision: {decision}**",
        "",
        *[f"- {r}" for r in reasons],
        "",
        "## Scorecard",
        "| Metric | Production | Candidate |",
        "|---|---|---|",
        *[f"| {m} | {b} | {c} |" for m, b, c in rows],
        "",
        "## Pass rate by risk area",
        "| Risk area | Production | Candidate |",
        "|---|---|---|",
        *[f"| {a} | {risk_b[a]:.0%} | {risk_c.get(a, 0):.0%} |" for a in risk_b],
        "",
        f"## Regressions ({len(regressed)}) and improvements ({len(improved)})",
    ]
    for b, c in regressed[:8]:
        out += [f"### {c.id} ({c.risk_area})", f"- errors: {', '.join(c.errors) or 'field mismatch'}", "```", f"baseline:  {b.output}", f"candidate: {c.output}", "```"]
    return "\n".join(out) + "\n"


def pr_comment(decision: str, reasons: list[str], base: dict, cand: dict, n_reg: int) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "BLOCK": "⛔"}[decision]
    return (
        f"{icon} **Prompt safety gate: {decision}**\n\n"
        + "\n".join(f"- {r}" for r in reasons[:5])
        + f"\n\nPass rate {base['pass_rate']:.1%} → {cand['pass_rate']:.1%} · regressions: {n_reg} · "
        f"cost/call ${base['avg_cost_usd']:.6f} → ${cand['avg_cost_usd']:.6f}\n\nFull report: `reports/release_report.html`\n"
    )


def should_run(changed_files: list[str], watch_paths: list[str]) -> bool:
    return not changed_files or any(f.startswith(tuple(watch_paths)) for f in changed_files)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", default=str(ROOT / "prompts" / "crm_summary.prod.json"))
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--changed-files", nargs="*", default=[])
    args = ap.parse_args()
    cfg = read_json(ROOT / "gate_config.json")
    if not should_run(args.changed_files, cfg["watch_paths"]):
        print("No prompt or eval changes; gate skipped.")
        return
    bp, cp = read_json(args.baseline), read_json(args.candidate)
    golden = read_jsonl(GOLDEN)
    base_r = [score_case(bp, c) for c in golden]
    cand_r = [score_case(cp, c) for c in golden]
    base, cand = summarise(base_r), summarise(cand_r)
    decision, reasons = decide(base, cand, cfg)
    regressed, improved = diff_cases(base_r, cand_r)
    md = render_markdown(bp, cp, base, cand, decision, reasons, regressed, improved, by_risk(base_r), by_risk(cand_r))
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "release_report.md").write_text(md, encoding="utf-8")
    (REPORTS / "release_report.html").write_text(f"<html><body><pre>{html.escape(md)}</pre></body></html>", encoding="utf-8")
    (REPORTS / "pr_comment.md").write_text(pr_comment(decision, reasons, base, cand, len(regressed)), encoding="utf-8")
    (REPORTS / "run.json").write_text(json.dumps({"baseline": base, "candidate": cand, "decision": decision}, indent=2), encoding="utf-8")

    print(f"Prompt {cp['id']}: {bp['version']} (prod) vs {cp['version']} (candidate) on {len(golden)} golden cases")
    for k in ("pass_rate", "schema_validity", "field_accuracy"):
        print(f"  {k:<16} {base[k]:7.1%} -> {cand[k]:7.1%}")
    print(f"  {'safety_failures':<16} {base['safety_failures']:7d} -> {cand['safety_failures']:7d}")
    print(f"  {'avg_cost_usd':<16} {base['avg_cost_usd']:.6f} -> {cand['avg_cost_usd']:.6f}")
    print(f"  {'p95_latency_ms':<16} {base['p95_latency_ms']:7.0f} -> {cand['p95_latency_ms']:7.0f}")
    print(f"  regressions={len(regressed)} improvements={len(improved)}")
    print(f"DECISION: {decision}")
    for r in reasons:
        print(f"  - {r}")
    sys.exit(1 if decision == "BLOCK" else 0)


if __name__ == "__main__":
    main()
