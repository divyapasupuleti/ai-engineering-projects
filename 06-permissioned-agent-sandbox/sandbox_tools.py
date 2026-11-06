"""Tool registry: every tool declares its schema, risk level, allowed roles and rate limit."""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
MAX_FILE_BYTES = 20_000

RISK_LEVELS = ("low", "medium", "high")


class ToolError(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, type]
    risk: str
    roles: set[str]
    rate_limit_per_run: int
    fn: Callable[..., Any]
    writes: bool = False
    returns_untrusted: bool = False
    approval_roles: set[str] = field(default_factory=lambda: {"manager", "admin"})

    def validate(self, args: dict[str, Any]) -> list[str]:
        errors = [f"missing arg '{k}'" for k in self.params if k not in args]
        errors += [f"unexpected arg '{k}'" for k in args if k not in self.params]
        errors += [
            f"arg '{k}' must be {t.__name__}"
            for k, t in self.params.items()
            if k in args and not isinstance(args[k], t)
        ]
        return errors


# ---------------------------------------------------------------- calculator

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 10:
            raise ToolError("exponent too large")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ToolError(f"unsupported expression element: {type(node).__name__}")


def calculator(expression: str) -> float:
    """Arithmetic only, via AST whitelist: no names, calls or attributes, so no eval() escape."""
    if len(expression) > 200:
        raise ToolError("expression too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"invalid expression: {exc.msg}") from exc
    return round(_eval(tree), 6)


# ---------------------------------------------------------------- files


def read_file(path: str) -> str:
    """Read a file inside workspace/ only; resolves symlinks and '..' before checking."""
    target = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in target.parents and target != WORKSPACE.resolve():
        raise ToolError(f"path escapes sandbox: {path}")
    if not target.is_file():
        raise ToolError(f"no such file: {path}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ToolError("file too large")
    return target.read_text()


def search_kb(query: str) -> list[str]:
    kb = (WORKSPACE / "kb.md").read_text().split("\n\n")
    terms = set(re.findall(r"[a-z]+", query.lower()))
    scored = sorted(kb, key=lambda p: -len(terms & set(re.findall(r"[a-z]+", p.lower()))))
    return [p.strip() for p in scored[:2]]


# ---------------------------------------------------------------- side effects (simulated)

OUTBOX: list[dict] = []
TICKETS: list[dict] = []
RECORDS = {"cust-1001": "Acme Ltd", "cust-1002": "Globex", "cust-1003": "Initech"}


def create_ticket(title: str, priority: str) -> dict:
    if priority not in ("low", "medium", "high"):
        raise ToolError("priority must be low|medium|high")
    ticket = {"id": f"T-{len(TICKETS) + 1:04d}", "title": title, "priority": priority}
    TICKETS.append(ticket)
    return ticket


def send_email(to: str, subject: str, body: str) -> dict:
    if not re.fullmatch(r"[\w.+-]+@company\.com", to):
        raise ToolError("external recipients are not allowed")
    msg = {"to": to, "subject": subject, "body": body[:500]}
    OUTBOX.append(msg)
    return {"queued": True, "to": to}


def delete_record(record_id: str) -> dict:
    if record_id not in RECORDS:
        raise ToolError(f"unknown record {record_id}")
    return {"deleted": record_id, "name": RECORDS.pop(record_id)}


REGISTRY: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec("calculator", "Evaluate arithmetic", {"expression": str}, "low",
                 {"viewer", "analyst", "support", "admin"}, 5, calculator),
        ToolSpec("read_file", "Read a workspace file", {"path": str}, "low",
                 {"analyst", "support", "admin"}, 5, read_file, returns_untrusted=True),
        ToolSpec("search_kb", "Search the help-center KB", {"query": str}, "low",
                 {"viewer", "analyst", "support", "admin"}, 5, search_kb, returns_untrusted=True),
        ToolSpec("create_ticket", "Open a support ticket", {"title": str, "priority": str}, "medium",
                 {"support", "admin"}, 3, create_ticket, writes=True),
        ToolSpec("send_email", "Send internal email", {"to": str, "subject": str, "body": str}, "high",
                 {"analyst", "support", "admin"}, 2, send_email, writes=True),
        ToolSpec("delete_record", "Delete a customer record", {"record_id": str}, "high",
                 {"admin"}, 1, delete_record, writes=True, approval_roles={"admin"}),
    ]
}
