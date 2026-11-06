"""Natural language -> validated, confirmed, chained API calls against an OpenAPI spec."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from common.embeddings import cosine, embed
from mock_api import MockAPI

SPEC_PATH = Path(__file__).resolve().parent / "api" / "openapi.json"
WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
REF_RE = re.compile(r"^\$(\d+)\.(.+)$")


# ---------------------------------------------------------------- spec + endpoint retrieval


@dataclass
class Operation:
    op_id: str
    method: str
    path: str
    summary: str
    description: str
    params: list[dict]
    body_schema: dict | None

    @property
    def card(self) -> str:
        return f"{self.op_id}: {self.method} {self.path} - {self.summary}. {self.description}"


def load_operations(path: Path = SPEC_PATH) -> dict[str, Operation]:
    spec = json.loads(path.read_text())
    ops = {}
    for p, methods in spec["paths"].items():
        for m, op in methods.items():
            ops[op["operationId"]] = Operation(
                op["operationId"], m.upper(), p, op["summary"], op.get("description", ""),
                op.get("parameters", []), (op.get("requestBody") or {}).get("schema"),
            )
    return ops


class EndpointIndex:
    """Only the top-k endpoint cards go into the model's context, so large specs stay cheap and focused."""

    def __init__(self, ops: dict[str, Operation]) -> None:
        self.ops = ops
        self.vecs = {k: embed(o.card) for k, o in ops.items()}

    def select(self, request: str, k: int = 3) -> list[str]:
        q = embed(request)
        return sorted(self.vecs, key=lambda k: -cosine(q, self.vecs[k]))[:k]


# ---------------------------------------------------------------- minimal JSON-schema validation


def validate(value: Any, schema: dict, where: str = "") -> list[str]:
    errs = []
    t = schema.get("type")
    types = {"string": str, "number": (int, float), "integer": int, "object": dict, "boolean": bool}
    if t and not isinstance(value, types[t]):
        return [f"{where or 'value'} must be {t}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where} must be one of {schema['enum']} (got {value!r})")
    if t == "string":
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{where} shorter than {schema['minLength']} chars")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{where} longer than {schema['maxLength']} chars")
    if t == "number":
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{where} below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{where} above maximum {schema['maximum']}")
    if t == "object":
        errs += [f"{where}.{r} is required" for r in schema.get("required", []) if r not in value]
        for k, v in value.items():
            if k in schema.get("properties", {}):
                errs += validate(v, schema["properties"][k], f"{where}.{k}" if where else k)
    return errs


def validate_call(op: Operation, args: dict) -> list[str]:
    errs = []
    for p in op.params:
        if p.get("required") and p["name"] not in args:
            errs.append(f"missing {p['in']} param '{p['name']}'")
        elif p["name"] in args:
            errs += validate(args[p["name"]], p["schema"], p["name"])
    if op.body_schema:
        errs += validate(args.get("body", {}), op.body_schema, "body")
    return errs


# ---------------------------------------------------------------- planner (LLM stand-in)


@dataclass
class Step:
    op_id: str
    args: dict[str, Any]
    expect_one: bool = False


NAME_RE = re.compile(r"\b(?i:for|of|customer|account|move|upgrade|downgrade|delete|find|up)\s+(?i:the\s+)?(?i:customer\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)")
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:eur|euro|euros|€)", re.I)


def extract_customer(text: str) -> str | None:
    for m in NAME_RE.finditer(text):
        name = m.group(1).strip()
        if name.lower() not in {"the", "api", "eur"}:
            return name
    return None


def plan(request: str, allowed_ops: set[str]) -> tuple[list[Step], str | None]:
    r = request.lower()
    name = extract_customer(request)
    find = Step("searchCustomers", {"search": name or ""}, expect_one=True)
    cid = "$0.items.0.id"
    if re.search(r"\b(delete|remove)\b.*\b(customer|account)\b", r):
        primary = [Step("deleteCustomer", {"customer_id": cid})]
    elif "refund" in r:
        amount = AMOUNT_RE.search(request)
        reason = request.split("because", 1)[1].strip(" .") if "because" in r else "customer request"
        primary = [
            Step("listInvoices", {"customer_id": cid, "status": "paid"}),
            Step("refundInvoice", {"invoice_id": "$1.items.0.id", "body": {
                "amount": float(amount.group(1)) if amount else "$1.items.0.amount", "reason": reason}}),
        ]
    elif re.search(r"\b(ticket|issue)\b", r):
        prio = re.search(r"\b(\w+) priority\b", r)
        title = request.split(" about ", 1)[1].strip(" .") if " about " in request else ""
        primary = [Step("createTicket", {"body": {"customer_id": cid, "title": title,
                                                  "priority": prio.group(1) if prio else "medium"}})]
    elif m := re.search(r"\b(?:upgrade|downgrade|move|switch|change)\b.*?\b(\w+) plan\b", r):
        primary = [Step("updateCustomer", {"customer_id": cid, "body": {"plan": m.group(1)}})]
    elif re.search(r"\b(invoices?|billing|charges)\b", r):
        status = next((s for s in ("unpaid", "overdue", "paid") if s in r), None)
        args = {"customer_id": cid, **({"status": status} if status else {})}
        primary = [Step("listInvoices", args)]
    elif re.search(r"\b(usage|seats|storage)\b", r):
        primary = [Step("getUsage", {"customer_id": cid})]
    elif re.search(r"\b(find|look up|show|search)\b", r) and name:
        return [find], None
    else:
        return [], "unsupported request: no matching API capability"
    if primary[-1].op_id not in allowed_ops:
        return [], f"endpoint {primary[-1].op_id} not in retrieved context"
    if not name:
        return [], "which customer do you mean?"
    return [find, *primary], None


# ---------------------------------------------------------------- execution


@dataclass
class Result:
    status: str  # done | dry_run | needs_clarification | not_found | validation_error | blocked | cancelled | api_error | unsupported
    message: str
    calls: list[dict] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


def _deref(value: Any, results: list[Any]) -> Any:
    if isinstance(value, dict):
        return {k: _deref(v, results) for k, v in value.items()}
    if isinstance(value, str) and (m := REF_RE.match(value)):
        cur = results[int(m.group(1))]
        for part in m.group(2).split("."):
            cur = cur[int(part)] if part.isdigit() else cur[part]
        return cur
    return value


def build_request(op: Operation, args: dict) -> dict:
    path = op.path
    query = {}
    for p in op.params:
        if p["name"] in args:
            if p["in"] == "path":
                path = path.replace("{" + p["name"] + "}", str(args[p["name"]]))
            else:
                query[p["name"]] = args[p["name"]]
    return {"method": op.method, "path": path, "query": query, "body": args.get("body")}


class Assistant:
    def __init__(self, api: MockAPI | None = None, role: str = "support") -> None:
        self.ops = load_operations()
        self.index = EndpointIndex(self.ops)
        self.api = api or MockAPI()
        self.role = role

    def handle(self, request: str, confirm: Callable[[dict], bool] = lambda req: True, dry_run: bool = False) -> Result:
        retrieved = self.index.select(request, k=3)
        steps, problem = plan(request, set(retrieved) | {"searchCustomers"})
        res = Result("unsupported", problem or "", retrieved=retrieved, plan=[s.op_id for s in steps])
        if problem:
            res.status = "needs_clarification" if "which customer" in problem else "unsupported"
            return res
        if dry_run:
            res.status = "dry_run"
            res.calls = [build_request(self.ops[s.op_id], s.args) for s in steps]
            res.message = "Planned calls (references like $0.items.0.id resolve at run time)"
            return res
        results: list[Any] = []
        for s in steps:
            op = self.ops[s.op_id]
            try:
                args = _deref(s.args, results)
            except (IndexError, KeyError):
                res.status, res.message = "not_found", "a previous step returned no matching record"
                return res
            errs = validate_call(op, args)
            if errs:
                res.status, res.message = "validation_error", "; ".join(errs)
                return res
            req = build_request(op, args)
            if op.method == "DELETE" and self.role != "admin":
                res.status, res.message = "blocked", f"{op.op_id} requires admin role (you are {self.role})"
                res.calls.append({**req, "executed": False})
                return res
            if op.method in WRITE_METHODS and not confirm(req):
                res.status, res.message = "cancelled", f"user declined {op.method} {req['path']}"
                res.calls.append({**req, "executed": False})
                return res
            resp = self.api.call(req["method"], req["path"], req["query"], req["body"])
            res.calls.append({**req, "executed": True, "status": resp.status})
            if resp.status >= 400:
                res.status, res.message = "api_error", resp.body.get("error", "error")
                return res
            if s.expect_one:
                n = resp.body["count"]
                if n == 0:
                    res.status, res.message = "not_found", f"no customer matches '{args['search']}'"
                    return res
                if n > 1 and len(steps) > 1:
                    names = " or ".join(c["name"] for c in resp.body["items"])
                    res.status, res.message = "needs_clarification", f"did you mean {names}?"
                    return res
            results.append(resp.body)
        res.status, res.message = "done", summarise(steps[-1].op_id, results[-1])
        return res


def summarise(op_id: str, body: Any) -> str:
    if op_id == "searchCustomers":
        return "; ".join(f"{c['name']} ({c['id']}, {c['plan']}, {c['status']})" for c in body["items"])
    if op_id == "listInvoices":
        return f"{body['count']} invoice(s): " + ", ".join(f"{i['id']} {i['amount']} EUR {i['status']}" for i in body["items"])
    if op_id == "refundInvoice":
        return f"refund {body['id']} of {body['amount']} EUR issued on {body['invoice_id']}"
    if op_id == "createTicket":
        return f"ticket {body['id']} ({body['priority']}) opened: {body['title']}"
    if op_id == "updateCustomer":
        return f"{body['name']} is now on the {body['plan']} plan"
    if op_id == "getUsage":
        return f"{body['api_requests']:,} API requests, {body['seats_used']} seats, {body['storage_gb']} GB"
    return json.dumps(body)[:200]
