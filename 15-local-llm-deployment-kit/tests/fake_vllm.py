"""Minimal stand-in for a vLLM OpenAI server: streaming chat with usage, /health, /version and vLLM-named metrics.

Accepts and ignores vLLM CLI flags so matrix.run_one can launch it like the real server.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"running": 0, "hits": 0, "queries": 0, "prefix": False}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._json(200, {})
        if self.path == "/version":
            return self._json(200, {"version": "0.0-fake"})
        if self.path == "/v1/models":
            return self._json(200, {"data": [{"id": "fake/Qwen-7B"}]})
        if self.path == "/metrics":
            with LOCK:
                body = (f"# HELP vllm:kv_cache_usage_perc fraction\n"
                        f'vllm:kv_cache_usage_perc{{model_name="fake"}} {min(1.0, STATE["running"] * 0.1)}\n'
                        f'vllm:num_requests_waiting{{model_name="fake"}} {max(0, STATE["running"] - 4)}\n'
                        f'vllm:prefix_cache_hits_total{{model_name="fake"}} {STATE["hits"]}\n'
                        f'vllm:prefix_cache_queries_total{{model_name="fake"}} {STATE["queries"]}\n')
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {})

    def do_POST(self):  # noqa: N802
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        n = req["max_tokens"]
        prompt_tokens = len(req["messages"][0]["content"].split())
        with LOCK:
            STATE["running"] += 1
            STATE["queries"] += prompt_tokens
            STATE["hits"] += prompt_tokens // 2 if STATE["prefix"] else 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        time.sleep(0.01)
        for i in range(n):
            chunk = {"choices": [{"index": 0, "delta": {"content": f"t{i} "}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.01)
        usage = {"choices": [], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": n}}
        self.wfile.write(f"data: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())
        with LOCK:
            STATE["running"] -= 1
        self.close_connection = True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--fake-prefix-hits", action="store_true")
    args, _ = ap.parse_known_args()
    STATE["prefix"] = args.fake_prefix_hits
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
