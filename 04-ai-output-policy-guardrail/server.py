#!/usr/bin/env python3
"""Sidecar HTTP API (stdlib). POST /check with a CheckRequest JSON body; GET /stats.

    python server.py --port 8084
    curl -s -X POST localhost:8084/check -d '{"feature":"support_reply","prompt":"x","output":"mail me at a@b.com"}'
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from guardrail import CheckRequest, GuardrailService  # noqa: E402

SERVICE = GuardrailService()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/stats":
            self._send(200, SERVICE.stats())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/check":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            decision = SERVICE.check(CheckRequest(**body))
        except (json.JSONDecodeError, TypeError) as exc:
            return self._send(400, {"error": str(exc)})
        self._send(200, decision.to_dict())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8084)
    args = ap.parse_args()
    print(f"Guardrail sidecar on http://127.0.0.1:{args.port} (policy {SERVICE.version})")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
