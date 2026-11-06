"""Agent runtime: plan -> per-step permission check -> execute / pause for approval -> persist -> resume.

States: planned -> running -> (awaiting_approval -> running)* -> completed | failed | denied | rejected
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from policy import check_call, scan_untrusted
from sandbox_tools import REGISTRY, ToolError

RUNS_DIR = Path(__file__).resolve().parent / "runs"
MAX_STEPS = 8
TEMPLATE_RE = re.compile(r"\{\{(sum|last):?(\d*)\}\}")


# ---------------------------------------------------------------- planner (LLM stand-in)


def plan(task: str) -> list[dict[str, Any]]:
    """Deterministic planner standing in for a function-calling model; emits tool calls only."""
    steps: list[dict[str, Any]] = []
    for clause in re.split(r",? then |; | and then ", task.strip().rstrip(".")):
        c = clause.strip()
        if m := re.search(r"\bread (\S+)", c, re.I):
            steps.append({"tool": "read_file", "args": {"path": m.group(1)}})
        elif re.search(r"\b(calculate|compute|add up)\b.*\btotal\b", c, re.I) and steps:
            steps.append({"tool": "calculator", "args": {"expression": f"{{{{sum:{len(steps)}}}}}"}})
        elif m := re.search(r"\b(?:calculate|compute|what is)\s+(.+)", c, re.I):
            steps.append({"tool": "calculator", "args": {"expression": m.group(1).strip()}})
        elif m := re.search(r"\bsearch (?:the kb |kb )?for (.+)", c, re.I):
            steps.append({"tool": "search_kb", "args": {"query": m.group(1)}})
        elif m := re.search(r"\b(?:open|create) an? (low|medium|high) priority ticket (?:about|for) (.+)", c, re.I):
            steps.append({"tool": "create_ticket", "args": {"title": m.group(2), "priority": m.group(1).lower()}})
        elif m := re.search(r"\bemail (?:the \w+ )?to (\S+)", c, re.I):
            steps.append({"tool": "send_email", "args": {"to": m.group(1), "subject": "Agent result", "body": "{{last}}"}})
        elif m := re.search(r"\bdelete (?:record )?(\S+)", c, re.I):
            steps.append({"tool": "delete_record", "args": {"record_id": m.group(1)}})
        elif m := re.search(r"\buse (\w+)", c, re.I):
            steps.append({"tool": m.group(1), "args": {}})
    return steps[:MAX_STEPS]


def _resolve(value: Any, results: list[Any]) -> Any:
    if not isinstance(value, str):
        return value

    def sub(m: re.Match) -> str:
        kind, idx = m.group(1), m.group(2)
        source = results[int(idx) - 1] if idx else (results[-1] if results else "")
        if kind == "sum":
            nums = re.findall(r"\b\d+(?:\.\d+)?\b", str(source))
            return "+".join(nums) or "0"
        return str(source)

    return TEMPLATE_RE.sub(sub, value)


# ---------------------------------------------------------------- run state


def _save(run: dict) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"{run['run_id']}.json").write_text(json.dumps(run, indent=2, default=str))


def load_run(run_id: str) -> dict:
    return json.loads((RUNS_DIR / f"{run_id}.json").read_text())


def _event(run: dict, kind: str, **data: Any) -> None:
    run["trace"].append({"t": round(time.time(), 3), "step": run["cursor"], "event": kind, **data})


def start(task: str, role: str, user: str = "demo-user") -> dict:
    run = {
        "run_id": uuid.uuid4().hex[:10], "task": task, "role": role, "user": user,
        "status": "planned", "plan": plan(task), "cursor": 0, "results": [],
        "calls": {}, "tainted": False, "approvals": [], "trace": [],
    }
    _event(run, "planned", steps=[s["tool"] for s in run["plan"]])
    if not run["plan"]:
        run["status"] = "failed"
        _event(run, "no_plan", reason="no supported tool matched the task")
        _save(run)
        return run
    return _execute(run)


def _execute(run: dict, approved_step: int | None = None) -> dict:
    run["status"] = "running"
    while run["cursor"] < len(run["plan"]):
        step = run["plan"][run["cursor"]]
        args = {k: _resolve(v, run["results"]) for k, v in step["args"].items()}
        decision = check_call(step["tool"], args, run["role"], run["calls"], run["tainted"])
        _event(run, "policy", tool=step["tool"], verdict=decision.verdict, reason=decision.reason)
        if decision.verdict == "deny":
            run["status"] = "denied"
            break
        if decision.verdict == "needs_approval" and approved_step != run["cursor"]:
            run["status"] = "awaiting_approval"
            run["pending"] = {"tool": step["tool"], "args": args, "reason": decision.reason}
            break
        tool = REGISTRY[step["tool"]]
        run["calls"][tool.name] = run["calls"].get(tool.name, 0) + 1
        try:
            started = time.perf_counter()
            result = tool.fn(**args)
            _event(run, "tool_result", tool=tool.name, ms=round((time.perf_counter() - started) * 1000, 2),
                   preview=str(result)[:120])
        except ToolError as exc:
            _event(run, "tool_error", tool=tool.name, error=str(exc))
            run["status"] = "failed"
            break
        if tool.returns_untrusted:
            hits = scan_untrusted(str(result))
            if hits:
                run["tainted"] = True
                _event(run, "injection_flagged", tool=tool.name, matches=hits)
        run["results"].append(result)
        run["cursor"] += 1
        run.pop("pending", None)
    else:
        run["status"] = "completed"
    _event(run, "status", status=run["status"])
    _save(run)
    return run


def resume(run_id: str, approver: str, approver_role: str, approve: bool, note: str = "") -> dict:
    run = load_run(run_id)
    if run["status"] != "awaiting_approval":
        raise ValueError(f"run {run_id} is {run['status']}, not awaiting approval")
    tool = REGISTRY[run["pending"]["tool"]]
    if approver_role not in tool.approval_roles:
        raise PermissionError(f"role '{approver_role}' cannot approve {tool.name}")
    run["approvals"].append({"step": run["cursor"], "tool": tool.name, "approver": approver,
                             "approved": approve, "note": note, "t": round(time.time(), 3)})
    _event(run, "approval", approver=approver, approved=approve)
    if not approve:
        run["status"] = "rejected"
        _event(run, "status", status="rejected")
        _save(run)
        return run
    return _execute(run, approved_step=run["cursor"])
