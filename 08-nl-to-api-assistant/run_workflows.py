#!/usr/bin/env python3
"""Golden workflow suite: endpoint retrieval, plan correctness and outcome for each request.

    python run_workflows.py            # full suite
    python run_workflows.py --ask "Show unpaid invoices for Globex" [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from assistant import Assistant  # noqa: E402
from common.io import read_jsonl  # noqa: E402


def run_suite() -> int:
    cases = read_jsonl(ROOT / "data" / "workflows.jsonl")
    plan_ok = status_ok = retrieval_ok = retrieval_n = 0
    writes_executed = writes_proposed = 0
    for c in cases:
        bot = Assistant()
        res = bot.handle(c["request"], confirm=lambda req, ok=c["confirm"]: ok)
        p_ok = res.plan == c["expected_ops"]
        s_ok = res.status == c["expected_status"]
        plan_ok += p_ok
        status_ok += s_ok
        if c["expected_ops"]:
            retrieval_n += 1
            retrieval_ok += c["expected_ops"][-1] in res.retrieved
        for call in res.calls:
            if call["method"] != "GET":
                writes_proposed += 1
                writes_executed += call.get("executed", False)
        mark = "PASS" if p_ok and s_ok else "FAIL"
        print(f"{mark} {c['id']} [{res.status:<19}] {c['request'][:62]:<62} -> {res.message[:70]}")
    n = len(cases)
    print(f"\nPlan exact-match: {plan_ok}/{n} · outcome match: {status_ok}/{n} · "
          f"endpoint retrieval recall@3: {retrieval_ok}/{retrieval_n}")
    print(f"Write calls proposed: {writes_proposed}, executed: {writes_executed} "
          f"(rest stopped by confirmation, role or validation)")
    return 0 if plan_ok == status_ok == n else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ask")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--role", default="support")
    args = ap.parse_args()
    if not args.ask:
        sys.exit(run_suite())
    bot = Assistant(role=args.role)
    res = bot.handle(args.ask, confirm=lambda req: input(f"Execute {req['method']} {req['path']} {req['body']}? [y/N] ").lower() == "y",
                     dry_run=args.dry_run)
    print(f"retrieved endpoints: {res.retrieved}\nplan: {res.plan}\nstatus: {res.status}\n{res.message}")
    for call in res.calls:
        print(f"  {call}")


if __name__ == "__main__":
    main()
