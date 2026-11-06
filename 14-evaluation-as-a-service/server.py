"""Stdlib HTTP API for the eval service.

    POST /evaluate  {"judge": "judge-large", "judge_pass_at": 4, "system_version": "adhoc",
                     "items": [{"id": "x", "key_facts": ["14 days"], "output": "Refunds within 14 days. [kb:refund]"}]}
    GET  /runs
    GET  /runs/<run_id>
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from service import EvalService


def make_handler(svc: EvalService):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict | list) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/runs":
                return self._send(200, svc.runs())
            if self.path.startswith("/runs/"):
                run_id = self.path.split("/")[2]
                try:
                    return self._send(200, {**svc.run(run_id), "by_category": svc.by_category(run_id)})
                except TypeError:
                    return self._send(404, {"error": "run not found"})
            self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/evaluate":
                return self._send(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                items = req["items"]
                for it in items:
                    if not it.get("key_facts") or "output" not in it:
                        raise ValueError("each item needs key_facts and output")
                run_id = svc.evaluate(items, req.get("judge", "judge-large"), int(req.get("judge_pass_at", 4)),
                                      req.get("system_version", "adhoc"))
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"error": str(exc)})
            self._send(200, svc.run(run_id))

        def log_message(self, *args):
            pass

    return Handler


def serve(svc: EvalService, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(svc))
