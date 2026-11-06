#!/usr/bin/env python3
"""CLI for the sandboxed agent.

    python run_agent.py start --role analyst "read q3_numbers.txt, then calculate the total, then email the result to finance@company.com"
    python run_agent.py approve <run_id> --approver dana --approver-role manager
    python run_agent.py reject  <run_id> --approver dana --approver-role manager
    python run_agent.py show    <run_id>
"""

from __future__ import annotations

import argparse
import json

import agent


def summary(run: dict) -> str:
    lines = [f"run {run['run_id']} [{run['status']}] role={run['role']} task={run['task']!r}"]
    for e in run["trace"]:
        detail = {k: v for k, v in e.items() if k not in ("t", "event", "step")}
        lines.append(f"  step {e['step']} {e['event']:<18} {json.dumps(detail, default=str)[:140]}")
    if run.get("pending"):
        lines.append(f"  PENDING APPROVAL: {run['pending']['tool']} {run['pending']['args']} ({run['pending']['reason']})")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("task")
    s.add_argument("--role", default="analyst")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("run_id")
        p.add_argument("--approver", required=True)
        p.add_argument("--approver-role", required=True)
        p.add_argument("--note", default="")
    sub.add_parser("show").add_argument("run_id")
    args = ap.parse_args()

    if args.cmd == "start":
        run = agent.start(args.task, args.role)
    elif args.cmd in ("approve", "reject"):
        run = agent.resume(args.run_id, args.approver, args.approver_role, args.cmd == "approve", args.note)
    else:
        run = agent.load_run(args.run_id)
    print(summary(run))


if __name__ == "__main__":
    main()
