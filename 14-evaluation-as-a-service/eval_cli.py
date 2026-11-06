#!/usr/bin/env python3
"""Eval-as-a-service CLI.

    python eval_cli.py calibrate                       # judges vs humans, tune thresholds
    python eval_cli.py gate --baseline v1 --candidate v2   # exit 1 on BLOCK (use in CI)
    python eval_cli.py serve --port 8714
    python eval_cli.py demo                            # calibrate + gate + one HTTP round-trip
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from calibration import agreement, cohen_kappa, tune_threshold  # noqa: E402
from common.io import read_jsonl, write_json  # noqa: E402
from generate_data import generate  # noqa: E402
from judges import JUDGES, load_rubric  # noqa: E402
from server import serve  # noqa: E402
from service import EvalService  # noqa: E402

RUBRIC = ROOT / "rubrics" / "support_answer.v2.json"
DB = ROOT / "data" / "evals.db"
CALIB = ROOT / "reports" / "calibration.json"


def items() -> list[dict]:
    p = ROOT / "data" / "items.jsonl"
    return read_jsonl(p) if p.exists() else generate()


def calibrate() -> dict:
    rubric = load_rubric(RUBRIC)
    labelled = [it for it in items() if it["human"]]
    human = [(it["human"]["annotator_a"] + it["human"]["annotator_b"]) / 2 for it in labelled]
    a = [it["human"]["annotator_a"] for it in labelled]
    b = [it["human"]["annotator_b"] for it in labelled]
    ceiling = round(cohen_kappa([x >= rubric["pass_at"] for x in a], [x >= rubric["pass_at"] for x in b]), 3)
    print(f"Calibration set: {len(labelled)} items with two human annotators")
    print(f"  human-human agreement (pass/fail kappa): {ceiling}  <- ceiling for any judge")
    out = {"human_kappa": ceiling, "judges": {}}
    for name, j in JUDGES.items():
        scores = [j.judge(rubric, it, it["outputs"]["v1"], f"{it['id']}:v1").score for it in labelled]
        default = agreement(scores, human, rubric["pass_at"])
        t, k = tune_threshold(scores, human, rubric["pass_at"])
        cost = j.cost_per_call * 1000
        out["judges"][name] = {**default, "tuned_pass_at": t, "tuned_kappa": k, "cost_per_1k": cost}
        print(f"  {name:<12} kappa={default['kappa_pass']:<6} MAE={default['mae']:<6} spearman={default['spearman']:<6} "
              f"bias={default['bias']:+.2f}  -> tuned pass_at={t} kappa={k}  (${cost:.2f}/1k)")
    eligible = {n: v for n, v in out["judges"].items() if v["tuned_kappa"] >= 0.6}
    chosen = min(eligible, key=lambda n: eligible[n]["cost_per_1k"]) if eligible else max(out["judges"], key=lambda n: out["judges"][n]["tuned_kappa"])
    out["chosen"] = {"judge": chosen, "pass_at": out["judges"][chosen]["tuned_pass_at"]}
    print(f"  chosen: {chosen} with pass_at={out['chosen']['pass_at']} (cheapest judge with tuned kappa >= 0.6)")
    write_json(CALIB, out)
    return out


def gate(baseline: str, candidate: str) -> int:
    cal = json.loads(CALIB.read_text()) if CALIB.exists() else calibrate()
    judge, pass_at = cal["chosen"]["judge"], cal["chosen"]["pass_at"]
    svc = EvalService(DB, RUBRIC)
    data = items()
    rb = svc.evaluate(data, judge, pass_at, baseline)
    rc = svc.evaluate(data, judge, pass_at, candidate)
    b, c = svc.run(rb), svc.run(rc)
    print(f"\nBatch eval with {judge} (pass_at={pass_at}), rubric {b['rubric']}@{b['rubric_version']}, {b['n']} items")
    print(f"  {baseline}: mean {b['mean_score']:.2f}, pass rate {b['pass_rate']:.1%}  (run {rb})")
    print(f"  {candidate}: mean {c['mean_score']:.2f}, pass rate {c['pass_rate']:.1%}  (run {rc})  judge cost ${c['cost']:.3f}")
    cmp = svc.compare(rb, rc)
    print(f"  per item: {cmp['improved']} improved, {cmp['regressed']} regressed, {cmp['unchanged']} unchanged")
    cb, cc = svc.by_category(rb), svc.by_category(rc)
    print("  by category: " + ", ".join(f"{k} {cb[k]:.0%}->{cc[k]:.0%}" for k in cb))
    verdict, reasons = svc.gate(rb, rc)
    print(f"Gate: {verdict}" + (f" - {'; '.join(reasons)}" if reasons else ""))
    return 1 if verdict == "BLOCK" else 0


def http_roundtrip(port: int = 8714) -> None:
    svc = EvalService(DB, RUBRIC)
    srv = serve(svc, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    body = json.dumps({"judge": "judge-large", "judge_pass_at": 4, "system_version": "adhoc", "items": [
        {"id": "a", "key_facts": ["14 days", "original card"], "output": "Refunds are available within 14 days and go back to the original card. [kb:refund]"},
        {"id": "b", "key_facts": ["14 days", "original card"], "output": "Refunds are always instant."},
    ]}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/evaluate", body, {"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
    print(f"\nHTTP POST /evaluate -> run {resp['run_id']}: mean {resp['mean_score']:.1f}, pass rate {resp['pass_rate']:.0%}")
    srv.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calibrate")
    g = sub.add_parser("gate")
    g.add_argument("--baseline", default="v1")
    g.add_argument("--candidate", default="v2")
    sub.add_parser("serve").add_argument("--port", type=int, default=8714)
    sub.add_parser("demo")
    args = ap.parse_args()
    if args.cmd == "calibrate":
        calibrate()
    elif args.cmd == "gate":
        sys.exit(gate(args.baseline, args.candidate))
    elif args.cmd == "serve":
        print(f"serving on http://127.0.0.1:{args.port}")
        serve(EvalService(DB, RUBRIC), args.port).serve_forever()
    else:
        DB.unlink(missing_ok=True)
        calibrate()
        code = gate("v1", "v2")
        try:
            http_roundtrip()
        except OSError as exc:
            print(f"\nHTTP round-trip skipped: {exc}")
        print(f"\nCI exit code would be {code}")


if __name__ == "__main__":
    main()
