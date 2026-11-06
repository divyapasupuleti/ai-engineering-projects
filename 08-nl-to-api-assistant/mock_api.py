"""In-memory implementation of api/openapi.json so plans execute against something real."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

SEED = {
    "customers": {
        "c_101": {"id": "c_101", "name": "Globex Corporation", "plan": "pro", "status": "active"},
        "c_102": {"id": "c_102", "name": "Initech", "plan": "starter", "status": "active"},
        "c_103": {"id": "c_103", "name": "Acme Ltd", "plan": "enterprise", "status": "active"},
        "c_104": {"id": "c_104", "name": "Acme Labs", "plan": "starter", "status": "trial"},
        "c_105": {"id": "c_105", "name": "Umbrella Health", "plan": "pro", "status": "active"},
    },
    "invoices": {
        "inv_9001": {"id": "inv_9001", "customer_id": "c_101", "amount": 1250.0, "status": "paid", "date": "2026-10-01"},
        "inv_9002": {"id": "inv_9002", "customer_id": "c_101", "amount": 1250.0, "status": "unpaid", "date": "2026-11-01"},
        "inv_9003": {"id": "inv_9003", "customer_id": "c_102", "amount": 99.0, "status": "overdue", "date": "2026-09-01"},
        "inv_9004": {"id": "inv_9004", "customer_id": "c_105", "amount": 640.0, "status": "paid", "date": "2026-10-15"},
        "inv_9005": {"id": "inv_9005", "customer_id": "c_105", "amount": 640.0, "status": "paid", "date": "2026-09-15"},
    },
    "usage": {
        "c_101": {"api_requests": 812_400, "seats_used": 48, "storage_gb": 120},
        "c_102": {"api_requests": 9_200, "seats_used": 4, "storage_gb": 2},
        "c_105": {"api_requests": 230_000, "seats_used": 31, "storage_gb": 64},
    },
}


@dataclass
class Response:
    status: int
    body: Any


class MockAPI:
    def __init__(self) -> None:
        self.db = copy.deepcopy(SEED)
        self.tickets: list[dict] = []
        self.refunds: list[dict] = []
        self.log: list[tuple[str, str]] = []

    def call(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> Response:
        query, body = query or {}, body or {}
        self.log.append((method, path))
        parts = path.strip("/").split("/")
        if method == "GET" and parts == ["customers"]:
            term = query["search"].lower()
            items = [c for c in self.db["customers"].values() if term in c["name"].lower()]
            return Response(200, {"items": items, "count": len(items)})
        if parts[0] == "customers" and len(parts) == 2:
            cust = self.db["customers"].get(parts[1])
            if not cust:
                return Response(404, {"error": "customer not found"})
            if method == "PATCH":
                cust["plan"] = body["plan"]
                return Response(200, cust)
            if method == "DELETE":
                del self.db["customers"][parts[1]]
                return Response(204, {})
        if method == "GET" and parts == ["invoices"]:
            items = [i for i in self.db["invoices"].values() if i["customer_id"] == query["customer_id"]
                     and (not query.get("status") or i["status"] == query["status"])]
            items.sort(key=lambda i: i["date"], reverse=True)
            return Response(200, {"items": items, "count": len(items)})
        if method == "POST" and parts[0] == "invoices" and parts[-1] == "refund":
            inv = self.db["invoices"].get(parts[1])
            if not inv:
                return Response(404, {"error": "invoice not found"})
            if inv["status"] != "paid":
                return Response(422, {"error": f"invoice is {inv['status']}, only paid invoices can be refunded"})
            if body["amount"] > inv["amount"]:
                return Response(422, {"error": f"refund {body['amount']} exceeds invoice amount {inv['amount']}"})
            refund = {"id": f"rf_{len(self.refunds) + 1}", "invoice_id": inv["id"], **body}
            self.refunds.append(refund)
            return Response(201, refund)
        if method == "POST" and parts == ["tickets"]:
            ticket = {"id": f"tk_{len(self.tickets) + 1}", **body, "status": "open"}
            self.tickets.append(ticket)
            return Response(201, ticket)
        if method == "GET" and parts == ["usage"]:
            usage = self.db["usage"].get(query["customer_id"])
            return Response(200, usage) if usage else Response(404, {"error": "no usage for customer"})
        return Response(404, {"error": f"no route {method} {path}"})
