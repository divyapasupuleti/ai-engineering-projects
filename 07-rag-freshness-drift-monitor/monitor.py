#!/usr/bin/env python3
"""Compare the deployed index (built from kb_v1) with the current source (kb_v2) and write a freshness scorecard.

    python monitor.py --deployed data/kb_v1 --source data/kb_v2 --today 2026-11-06
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from common.io import read_jsonl, write_json  # noqa: E402
from drift import VectorIndex, run_probes  # noqa: E402
from freshness import CRITICALITY_WEIGHT, build_manifest, diff, manifest_to_json, stale_docs  # noqa: E402

SEVERITY_WEIGHT = {"material": 3.0, "minor": 1.0, "cosmetic": 0.0}


def build_index(manifest) -> VectorIndex:
    idx = VectorIndex()
    for c in manifest.values():
        idx.upsert(c)
    return idx


def incremental_rebuild(deployed: VectorIndex, source_manifest, changes) -> VectorIndex:
    cand = deployed.clone()
    cand.embed_calls = 0
    for ch in changes:
        if ch.kind == "removed":
            cand.delete(ch.chunk_id)
        elif ch.severity == "cosmetic":
            cand.entries[ch.chunk_id] = source_manifest[ch.chunk_id]
        else:
            cand.upsert(source_manifest[ch.chunk_id])
    return cand


def priority(change, traffic: int) -> float:
    return round(SEVERITY_WEIGHT[change.severity] * CRITICALITY_WEIGHT[change.criticality] * (1 + traffic / 100), 2)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deployed", default=str(ROOT / "data" / "kb_v1"))
    ap.add_argument("--source", default=str(ROOT / "data" / "kb_v2"))
    ap.add_argument("--today", default="2026-11-06")
    args = ap.parse_args()
    today = date.fromisoformat(args.today)

    deployed_manifest = build_manifest(Path(args.deployed))
    source_manifest = build_manifest(Path(args.source))
    deployed = build_index(deployed_manifest)
    changes = diff(deployed_manifest, source_manifest)
    candidate = incremental_rebuild(deployed, source_manifest, changes)
    probes = read_jsonl(ROOT / "data" / "probes.jsonl")
    results = run_probes(deployed, candidate, probes)

    traffic_by_chunk: dict[str, int] = {}
    for r in results:
        traffic_by_chunk[r.old_chunk] = traffic_by_chunk.get(r.old_chunk, 0) + r.traffic
    ranked = sorted(changes, key=lambda c: -priority(c, traffic_by_chunk.get(c.chunk_id, 0)))

    total_traffic = sum(r.traffic for r in results)
    fresh_before = sum(r.traffic for r in results if not r.deployed_stale) / total_traffic
    fresh_after = sum(r.traffic for r in results if r.candidate_correct) / total_traffic
    stale = stale_docs(source_manifest, today)
    material = [c for c in changes if c.severity == "material"]

    print(f"Deployed chunks: {len(deployed_manifest)} · source chunks: {len(source_manifest)}")
    print(f"Changes: {len(changes)} ({len(material)} material, "
          f"{sum(c.severity == 'minor' for c in changes)} minor, {sum(c.severity == 'cosmetic' for c in changes)} cosmetic)")
    print("\nPrioritised changes:")
    for c in ranked:
        t = traffic_by_chunk.get(c.chunk_id, 0)
        extra = f" {c.numbers_changed}" if c.numbers_changed else ""
        print(f"  p={priority(c, t):>5}  {c.kind:<8} {c.severity:<8} {c.chunk_id:<34} sem={c.semantic_change:<5} "
              f"traffic={t:<4} {c.reason}{extra}")
    print("\nProbes (deployed -> candidate):")
    for r in results:
        flag = "STALE" if r.deployed_stale else "ok   "
        fixed = "fixed" if r.deployed_stale and r.candidate_correct else ("ok" if r.candidate_correct else "WRONG")
        drift = "retrieval+answer" if r.retrieval_drift and r.answer_drift else ("answer" if r.answer_drift else ("retrieval" if r.retrieval_drift else "-"))
        print(f"  {r.probe_id} {flag} -> {fixed:<5} drift={drift:<16} {r.question}")
    print(f"\nTraffic-weighted freshness: {fresh_before:.0%} deployed -> {fresh_after:.0%} after incremental rebuild")
    print(f"Incremental rebuild re-embedded {candidate.embed_calls} of {len(source_manifest)} chunks "
          f"({1 - candidate.embed_calls / len(source_manifest):.0%} embedding cost avoided)")
    print("Docs past review SLA (180 days):", ", ".join(f"{d} ({o}, {a}d)" for d, o, a in stale) or "none")
    verdict = "REBUILD NOW" if any(c.criticality == "high" for c in material) or fresh_before < 0.9 else "OK"
    print(f"Verdict: {verdict}")

    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    write_json(reports / "source_manifest.json", manifest_to_json(source_manifest))
    lines = [
        "# RAG freshness scorecard", "",
        f"- Date: {today}", f"- Verdict: **{verdict}**",
        f"- Traffic-weighted freshness: {fresh_before:.0%} deployed, {fresh_after:.0%} after rebuild",
        f"- Re-embedded {candidate.embed_calls}/{len(source_manifest)} chunks", "",
        "## Prioritised changes", "", "| priority | chunk | kind | severity | semantic change | reason |", "|---|---|---|---|---|---|",
        *[f"| {priority(c, traffic_by_chunk.get(c.chunk_id, 0))} | {c.chunk_id} | {c.kind} | {c.severity} | {c.semantic_change} | {c.reason} {c.numbers_changed or ''} |" for c in ranked],
        "", "## Probes", "", "| probe | deployed answer | candidate answer | stale | fixed |", "|---|---|---|---|---|",
        *[f"| {r.probe_id} | {r.old_answer[:70]} | {r.new_answer[:70]} | {r.deployed_stale} | {r.candidate_correct} |" for r in results],
        "", "## Owners to notify", "", *[f"- {d}: {o}, last reviewed {a} days ago" for d, o, a in stale],
    ]
    (reports / "freshness_scorecard.md").write_text("\n".join(lines) + "\n")
    print("Wrote reports/freshness_scorecard.md and reports/source_manifest.json")


if __name__ == "__main__":
    main()
