#!/usr/bin/env python3
"""OpenAI-compatible gateway for local models.

    python llm_server.py --port 8815            # uses Ollama if running, else the simulator

    POST /v1/chat/completions   (OpenAI schema; "stream": true for SSE)
    GET  /v1/models  /healthz  /metrics (Prometheus)
    POST /admin/switch {"model": "llama3.1-8b:q8_0"}   POST /admin/rollback
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backends import BackendError, make_backend

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "models.json"
BUCKETS = [0.25, 0.5, 1, 2, 4, 8, 16, 32]


class Metrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counters: dict[tuple, float] = {}
        self.hist: dict[str, list[int]] = {}
        self.hist_sum: dict[str, float] = {}
        self.inflight = 0

    def inc(self, name: str, labels: dict, by: float = 1) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self.lock:
            self.counters[key] = self.counters.get(key, 0) + by

    def observe(self, model: str, seconds: float) -> None:
        with self.lock:
            h = self.hist.setdefault(model, [0] * (len(BUCKETS) + 1))
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    h[i] += 1
            h[-1] += 1
            self.hist_sum[model] = self.hist_sum.get(model, 0) + seconds

    def render(self, active: str) -> str:
        lines = ["# TYPE llm_requests_total counter", "# TYPE llm_tokens_generated_total counter",
                 "# TYPE llm_request_seconds histogram", "# TYPE llm_inflight_requests gauge"]
        with self.lock:
            for (name, labels), v in sorted(self.counters.items()):
                lab = ",".join(f'{k}="{val}"' for k, val in labels)
                lines.append(f"{name}{{{lab}}} {v:g}")
            for model, h in self.hist.items():
                for b, c in zip(BUCKETS, h):
                    lines.append(f'llm_request_seconds_bucket{{model="{model}",le="{b}"}} {c}')
                lines.append(f'llm_request_seconds_bucket{{model="{model}",le="+Inf"}} {h[-1]}')
                lines.append(f'llm_request_seconds_sum{{model="{model}"}} {self.hist_sum[model]:.3f}')
                lines.append(f'llm_request_seconds_count{{model="{model}"}} {h[-1]}')
            lines.append(f"llm_inflight_requests {self.inflight}")
        lines.append(f'llm_active_model_info{{model="{active}"}} 1')
        return "\n".join(lines) + "\n"


class ModelManager:
    def __init__(self, config_path: Path = CONFIG, prefer_ollama: bool = True) -> None:
        self.cfg = json.loads(config_path.read_text())
        self.prefer_ollama = prefer_ollama
        self.lock = threading.Lock()
        self.active = self.cfg["active"]
        self.previous = self.cfg.get("previous")
        self.backend = make_backend(self.active, self.cfg["profiles"][self.active], prefer_ollama)
        self.events: list[dict] = []

    @property
    def profile(self) -> dict:
        return self.cfg["profiles"][self.active]

    def switch(self, name: str) -> tuple[bool, str]:
        profiles, hw = self.cfg["profiles"], self.cfg["hardware"]
        if name not in profiles:
            return False, f"unknown model {name}"
        if profiles[name]["memory_gb"] > hw["memory_budget_gb"]:
            return False, f"{name} needs {profiles[name]['memory_gb']} GB > budget {hw['memory_budget_gb']} GB"
        candidate = make_backend(name, profiles[name], self.prefer_ollama)
        try:
            candidate.generate([{"role": "user", "content": "health check: reply ok"}], 4)
        except BackendError as exc:
            self.events.append({"t": time.time(), "event": "switch_failed", "model": name, "error": str(exc)})
            return False, f"health check failed, staying on {self.active}: {exc}"
        with self.lock:
            self.previous, self.active, self.backend = self.active, name, candidate
        self.events.append({"t": time.time(), "event": "switched", "from": self.previous, "to": name})
        return True, f"active model is now {name} (previous {self.previous})"

    def rollback(self) -> tuple[bool, str]:
        if not self.previous:
            return False, "no previous model to roll back to"
        target = self.previous
        ok, msg = self.switch(target)
        return ok, ("rolled back: " + msg) if ok else msg


def make_handler(mgr: ModelManager, metrics: Metrics):
    server_cfg = mgr.cfg["server"]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self) -> bool:
            token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            return token in server_cfg["api_keys"]

        def _body(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                return self._json(200, {"status": "ok", "model": mgr.active, "backend": type(mgr.backend).__name__})
            if self.path == "/metrics":
                data = metrics.render(mgr.active).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            if self.path == "/v1/models":
                return self._json(200, {"object": "list", "data": [
                    {"id": k, "object": "model", "owned_by": "local", "active": k == mgr.active}
                    for k in mgr.cfg["profiles"]]})
            self._json(404, {"error": {"message": "not found"}})

        def do_POST(self):  # noqa: N802
            if not self._authorised():
                return self._json(401, {"error": {"message": "invalid API key", "type": "auth"}})
            if self.path == "/admin/switch":
                ok, msg = mgr.switch(self._body().get("model", ""))
                return self._json(200 if ok else 409, {"ok": ok, "message": msg})
            if self.path == "/admin/rollback":
                ok, msg = mgr.rollback()
                return self._json(200 if ok else 409, {"ok": ok, "message": msg})
            if self.path != "/v1/chat/completions":
                return self._json(404, {"error": {"message": "not found"}})
            try:
                req = self._body()
                messages = req["messages"]
                max_tokens = int(req.get("max_tokens", 128))
            except (KeyError, ValueError, json.JSONDecodeError):
                return self._json(400, {"error": {"message": "messages is required", "type": "invalid_request"}})
            model = mgr.active
            with metrics.lock:
                limit = mgr.profile["max_parallel"] + server_cfg["max_queue"]
                if metrics.inflight >= limit:
                    rejected = True
                else:
                    rejected = False
                    metrics.inflight += 1
            if rejected:
                metrics.inc("llm_requests_total", {"model": model, "status": "429"})
                return self._json(429, {"error": {"message": "server busy, retry later", "type": "rate_limit"}})
            start = time.perf_counter()
            try:
                if req.get("stream"):
                    self._stream(model, messages, max_tokens)
                    status = "200"
                else:
                    gen = mgr.backend.generate(messages, max_tokens)
                    metrics.inc("llm_tokens_generated_total", {"model": model}, gen.completion_tokens)
                    status = "200"
                    self._json(200, {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
                        "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": gen.text},
                                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": gen.prompt_tokens, "completion_tokens": gen.completion_tokens,
                                  "total_tokens": gen.prompt_tokens + gen.completion_tokens},
                        "x_timing": {"ttft_ms": round(gen.ttft_ms, 1), "total_ms": round(gen.total_ms, 1)}})
            except BackendError as exc:
                status = "502"
                self._json(502, {"error": {"message": str(exc), "type": "backend"}})
            finally:
                with metrics.lock:
                    metrics.inflight -= 1
            metrics.inc("llm_requests_total", {"model": model, "status": status})
            metrics.observe(model, time.perf_counter() - start)

        def _stream(self, model: str, messages: list[dict], max_tokens: int) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            n = 0
            for tok in mgr.backend.stream(messages, max_tokens):
                n += 1
                chunk = {"id": cid, "object": "chat.completion.chunk", "model": model,
                         "choices": [{"index": 0, "delta": {"content": tok}, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True
            metrics.inc("llm_tokens_generated_total", {"model": model}, n)

        def log_message(self, *args):
            pass

    return Handler


def build_server(port: int, prefer_ollama: bool = True, host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, ModelManager, Metrics]:
    mgr, metrics = ModelManager(prefer_ollama=prefer_ollama), Metrics()
    srv = ThreadingHTTPServer((host, port), make_handler(mgr, metrics))
    srv.daemon_threads = True
    return srv, mgr, metrics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8815)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--simulate", action="store_true", help="never use Ollama")
    args = ap.parse_args()
    srv, mgr, _ = build_server(args.port, prefer_ollama=not args.simulate, host=args.host)
    print(f"serving {mgr.active} via {type(mgr.backend).__name__} on http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
