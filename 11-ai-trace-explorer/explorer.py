#!/usr/bin/env python3
"""Trace explorer CLI.

    python explorer.py simulate --n 300      # run the workflow, prompt v8 ships halfway through
    python explorer.py summary               # failure taxonomy, latency, prompt-version regression
    python explorer.py list --category schema_invalid
    python explorer.py show <trace_id>       # ASCII waterfall + root cause
    python explorer.py report                # reports/trace_report.html
    python explorer.py export                # failing traces -> evals/failed_cases.jsonl
"""

from __future__ import annotations

import argparse
import html
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from analyzer import analyse, root_cause, self_time  # noqa: E402
from common.io import write_jsonl  # noqa: E402
from common.stats import percentile  # noqa: E402
from trace_store import SimClock, TraceStore  # noqa: E402
from workflow import run_once  # noqa: E402

DB = ROOT / "data" / "traces.db"


def simulate(store: TraceStore, n: int, seed: int = 11) -> Counter:
    store.reset()
    rng, clock = random.Random(seed), SimClock()
    injected = Counter()
    for i in range(n):
        version = "support-v7" if i < n // 2 else "support-v8"
        res = run_once(rng, clock, prompt_version=version)
        store.save(res.recorder, res.meta)
        injected[res.injected] += 1
        clock.advance(rng.uniform(200, 2000))
    return injected


def classified(store: TraceStore):
    for t in store.traces():
        spans = store.spans(t["trace_id"])
        findings = analyse(spans)
        yield t, spans, findings, root_cause(findings)


def waterfall(spans: list[dict], width: int = 50) -> str:
    t0 = min(s["start_ms"] for s in spans)
    total = max(s["end_ms"] for s in spans) - t0 or 1
    depth = {}
    for s in spans:
        depth[s["span_id"]] = 0 if not s["parent_id"] else depth.get(s["parent_id"], 0) + 1
    lines = []
    for s in sorted(spans, key=lambda s: (s["start_ms"], -s["duration_ms"])):
        a = int((s["start_ms"] - t0) / total * width)
        b = max(a + 1, int((s["end_ms"] - t0) / total * width))
        bar = " " * a + ("X" if s["status"] == "error" else "#") * (b - a)
        name = "  " * depth[s["span_id"]] + s["name"]
        lines.append(f"  {name:<24} |{bar:<{width}}| {s['duration_ms']:>8.0f} ms {s['error'] or ''}")
    return "\n".join(lines)


def cmd_summary(store: TraceStore) -> None:
    rows = list(classified(store))
    cats = Counter(rc.category for _, _, _, rc in rows if rc)
    hard = [r for r in rows if r[0]["status"] == "error"]
    print(f"Traces: {len(rows)} · hard failures: {len(hard)} ({len(hard) / len(rows):.0%}) · "
          f"traces with any finding: {sum(1 for r in rows if r[2])}")
    print("\nRoot-cause taxonomy (owner -> suggested fix):")
    for cat, n in cats.most_common():
        f = next(rc for _, _, _, rc in rows if rc and rc.category == cat)
        print(f"  {n:>3}  {cat:<24} [{f.owner}] {f.hint}")
    expected = {"slow_rerank": {"latency_slo"}, "rate_limited": {"rate_limited", "rate_limited_recovered"}}
    scored = hit = false_alarms = 0
    for _, spans, _, rc in rows:
        fault = next(s for s in spans if s["parent_id"] is None)["attrs"]["injected_fault"]
        if fault != "none" and rc:
            scored += 1
            hit += rc.category in expected.get(fault, {fault})
        false_alarms += fault == "none" and rc is not None
    print(f"Root-cause accuracy vs injected faults: {hit}/{scored} ({hit / max(1, scored):.0%}) · "
          f"false alarms on healthy traces: {false_alarms}")
    durs = store.span_durations()
    print("\nLatency by span (p50 / p95 ms):")
    for name in ("request", "retrieve", "rerank", "llm.generate", "tool.lookup_order"):
        print(f"  {name:<20} {percentile(durs[name], 50):>8.0f} {percentile(durs[name], 95):>8.0f}")
    tot = defaultdict(float)
    for _, spans, _, _ in rows:
        for k, v in self_time(spans).items():
            tot[k] += v
    top = sorted(tot.items(), key=lambda kv: -kv[1])[:3]
    grand = sum(tot.values())
    print("Where time goes (self time):", ", ".join(f"{k} {v / grand:.0%}" for k, v in top))
    by_v = defaultdict(lambda: [0, 0, Counter()])
    for t, _, _, rc in rows:
        v = by_v[t["prompt_version"]]
        v[0] += 1
        v[1] += t["status"] == "error"
        if rc:
            v[2][rc.category] += 1
    print("\nBy prompt version:")
    for name, (n, err, c) in sorted(by_v.items()):
        print(f"  {name}: error rate {err / n:.1%} · schema_invalid {c['schema_invalid']} of {n}")
    v7, v8 = by_v.get("support-v7"), by_v.get("support-v8")
    if v7 and v8 and v8[2]["schema_invalid"] > 1.5 * max(1, v7[2]["schema_invalid"]):
        print(f"  REGRESSION: support-v8 schema_invalid {v8[2]['schema_invalid']} vs {v7[2]['schema_invalid']} in v7 "
              f"-> roll back or fix the prompt's JSON instructions")


def cmd_report(store: TraceStore) -> Path:
    rows = list(classified(store))
    cats = Counter(rc.category for _, _, _, rc in rows if rc)
    examples = {}
    for t, spans, findings, rc in rows:
        if rc and rc.category not in examples:
            examples[rc.category] = (t, spans, rc)
    css = ("body{font-family:system-ui;margin:24px;color:#1a1a1a}table{border-collapse:collapse;margin:8px 0}"
           "td,th{border:1px solid #ddd;padding:4px 8px;font-size:13px}.bar{height:14px;position:absolute;border-radius:3px}"
           ".row{position:relative;height:18px;margin:2px 0;background:#f5f7fa}.lbl{font-size:12px;width:200px;display:inline-block}"
           ".ok{background:#1e88e5}.error{background:#e53935}h2{margin-top:28px}")
    parts = [f"<html><head><meta charset='utf-8'><title>Trace report</title><style>{css}</style></head><body>",
             f"<h1>AI trace report</h1><p>{len(rows)} traces · {sum(1 for r in rows if r[0]['status'] == 'error')} hard failures</p>",
             "<h2>Root-cause taxonomy</h2><table><tr><th>category</th><th>count</th><th>owner</th><th>suggested fix</th></tr>"]
    for cat, n in cats.most_common():
        rc = examples[cat][2]
        parts.append(f"<tr><td>{cat}</td><td>{n}</td><td>{rc.owner}</td><td>{html.escape(rc.hint)}</td></tr>")
    parts.append("</table><h2>Example waterfall per category</h2>")
    for cat, (t, spans, rc) in examples.items():
        t0 = min(s["start_ms"] for s in spans)
        total = max(s["end_ms"] for s in spans) - t0 or 1
        parts.append(f"<h3>{cat} · trace {t['trace_id']} · {t['duration_ms']:.0f} ms</h3>"
                     f"<p>root cause: <b>{rc.span}</b> — {html.escape(rc.detail)}</p>")
        for s in sorted(spans, key=lambda s: s["start_ms"]):
            left = (s["start_ms"] - t0) / total * 100
            w = max(0.5, s["duration_ms"] / total * 100)
            parts.append(f"<div><span class='lbl'>{s['name']} ({s['duration_ms']:.0f} ms)</span>"
                         f"<div class='row' style='display:inline-block;width:60%'><div class='bar {s['status']}' "
                         f"style='left:{left:.2f}%;width:{w:.2f}%'></div></div></div>")
    parts.append("</body></html>")
    out = ROOT / "reports" / "trace_report.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(parts))
    return out


def cmd_export(store: TraceStore) -> int:
    rows = [
        {"id": f"trace-{t['trace_id']}", "input": t["user_input"], "feature": t["feature"],
         "prompt_version": t["prompt_version"], "failure": rc.category, "root_span": rc.span,
         "detail": rc.detail, "status": "draft"}
        for t, _, _, rc in classified(store) if rc and rc.category not in ("latency_slo", "rate_limited_recovered")
    ]
    return write_jsonl(ROOT / "evals" / "failed_cases.jsonl", rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("simulate").add_argument("--n", type=int, default=300)
    sub.add_parser("summary")
    sub.add_parser("list").add_argument("--category")
    sub.add_parser("show").add_argument("trace_id")
    sub.add_parser("report")
    sub.add_parser("export")
    sub.add_parser("demo")
    args = ap.parse_args()
    store = TraceStore(DB)

    if args.cmd in ("simulate", "demo"):
        injected = simulate(store, getattr(args, "n", 300))
        print(f"Simulated {sum(injected.values())} traces; injected faults: {dict(injected.most_common())}")
    if args.cmd in ("summary", "demo"):
        print()
        cmd_summary(store)
    if args.cmd == "list":
        for t, _, _, rc in classified(store):
            if args.category is None or (rc and rc.category == args.category):
                print(f"{t['trace_id']} {t['status']:<5} {t['duration_ms']:>8.0f} ms {rc.category if rc else '-':<22} {t['user_input']}")
    if args.cmd == "show":
        spans = store.spans(args.trace_id)
        print(waterfall(spans))
        for f in analyse(spans):
            print(f"  -> {f.category} at {f.span}: {f.detail}\n     fix ({f.owner}): {f.hint}")
    if args.cmd == "demo":
        t, spans, _, rc = next(r for r in classified(store) if r[3] and r[3].category == "rate_limited_recovered")
        print(f"\nExample trace {t['trace_id']} ({rc.category}):")
        print(waterfall(spans, width=40))
    if args.cmd in ("report", "demo"):
        print(f"\nWrote {cmd_report(store).relative_to(ROOT)}")
    if args.cmd in ("export", "demo"):
        print(f"Exported {cmd_export(store)} failing traces to evals/failed_cases.jsonl")


if __name__ == "__main__":
    main()
