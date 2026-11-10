#!/usr/bin/env python3
"""Load-test any OpenAI-compatible server (vLLM, TGI, SGLang, Ollama, this kit's gateway) with streaming requests.

Measures, per concurrency level:
    TTFT        time to first token (p50/p95/p99)
    ITL         inter-token latency, ms per output token after the first (p50/p95)
    E2E         full request latency (p50/p95)
    throughput  output tokens/s and requests/s across all streams
    server      peak KV-cache usage, peak queued requests, prefix-cache hit rate (vLLM /metrics)
    GPU         name, total and peak used memory (nvidia-smi, when present)

    python gpu/vllm_bench.py --base-url http://127.0.0.1:8000/v1 --label qwen7b-bf16
    python gpu/vllm_bench.py --base-url http://127.0.0.1:8815/v1 --api-key local-dev-key --label sim --quick
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS = ("customer export failed during the nightly sync because the warehouse token expired and the retry "
         "queue filled with duplicate invoices so finance asked support to explain refunds credits and the "
         "new billing plan while engineering investigated latency regressions in the reporting service").split()

KV_METRICS = ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc")
WAITING_METRIC = "vllm:num_requests_waiting"
PREFIX_HITS = ("vllm:prefix_cache_hits_total", "vllm:gpu_prefix_cache_hits_total")
PREFIX_QUERIES = ("vllm:prefix_cache_queries_total", "vllm:gpu_prefix_cache_queries_total")


def synthetic_prompt(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(words))


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 1)


def http_json(url: str, api_key: str, body: dict | None = None, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def detect_model(base_url: str, api_key: str) -> str:
    data = http_json(f"{base_url}/models", api_key).get("data", [])
    if not data:
        raise SystemExit(f"no models listed at {base_url}/models")
    return data[0]["id"]


def stream_one(base_url: str, api_key: str, model: str, prompt: str, max_tokens: int, fixed_output: bool) -> dict:
    body = {"model": model, "stream": True, "max_tokens": max_tokens, "temperature": 0.0,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": prompt}]}
    if fixed_output:
        body["ignore_eos"] = True  # vLLM extension: every request generates exactly max_tokens
    req = urllib.request.Request(f"{base_url}/chat/completions", json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    start = time.perf_counter()
    first = last = None
    chunks = 0
    usage = None
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                msg = json.loads(payload)
                if msg.get("usage"):
                    usage = msg["usage"]
                for choice in msg.get("choices") or []:
                    if (choice.get("delta") or {}).get("content"):
                        now = time.perf_counter()
                        first = first or now
                        last = now
                        chunks += 1
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"ok": False, "error": str(e)}
    end = time.perf_counter()
    if first is None:
        return {"ok": False, "error": "no tokens streamed"}
    out_tokens = (usage or {}).get("completion_tokens") or chunks
    return {"ok": True, "ttft_ms": (first - start) * 1000, "e2e_ms": (end - start) * 1000,
            "itl_ms": (last - first) * 1000 / (out_tokens - 1) if out_tokens > 1 else None,
            "output_tokens": out_tokens, "prompt_tokens": (usage or {}).get("prompt_tokens")}


def parse_prometheus(text: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name_part, _, value = line.rpartition(" ")
        name = name_part.split("{", 1)[0]
        try:
            totals[name] = totals.get(name, 0.0) + float(value)
        except ValueError:
            continue
    return totals


def first_metric(m: dict[str, float], names: tuple[str, ...]) -> float | None:
    return next((m[n] for n in names if n in m), None)


def gpu_snapshot() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    rows = [r.split(", ") for r in out.strip().splitlines() if r]
    if not rows:
        return None
    return {"name": rows[0][0], "count": len(rows),
            "memory_total_mib": sum(int(r[1]) for r in rows), "memory_used_mib": sum(int(r[2]) for r in rows)}


class ServerSampler(threading.Thread):
    """Polls /metrics and nvidia-smi while a load level runs and keeps the peaks."""

    def __init__(self, metrics_url: str | None, interval: float = 0.5):
        super().__init__(daemon=True)
        self.metrics_url, self.interval = metrics_url, interval
        self.stop_event = threading.Event()
        self.kv_peak = self.waiting_peak = self.gpu_mem_peak = None
        self.first = self.last = None

    def scrape(self) -> dict[str, float] | None:
        if not self.metrics_url:
            return None
        try:
            with urllib.request.urlopen(self.metrics_url, timeout=3) as r:
                return parse_prometheus(r.read().decode())
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return None

    def sample(self) -> None:
        m = self.scrape()
        if m is not None:
            self.first = self.first or m
            self.last = m
            kv, waiting = first_metric(m, KV_METRICS), m.get(WAITING_METRIC)
            if kv is not None:
                self.kv_peak = max(self.kv_peak or 0.0, kv)
            if waiting is not None:
                self.waiting_peak = max(self.waiting_peak or 0.0, waiting)
        g = gpu_snapshot()
        if g:
            self.gpu_mem_peak = max(self.gpu_mem_peak or 0, g["memory_used_mib"])

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.sample()
            self.stop_event.wait(self.interval)

    def finish(self) -> dict:
        self.stop_event.set()
        self.join(timeout=5)
        self.sample()
        hit_rate = None
        if self.first and self.last:
            hits = (first_metric(self.last, PREFIX_HITS) or 0) - (first_metric(self.first, PREFIX_HITS) or 0)
            queries = (first_metric(self.last, PREFIX_QUERIES) or 0) - (first_metric(self.first, PREFIX_QUERIES) or 0)
            hit_rate = round(hits / queries, 3) if queries > 0 else None
        kv = self.kv_peak
        return {"kv_cache_peak_pct": round(kv * 100, 1) if kv is not None and kv <= 1 else kv,
                "queued_peak": self.waiting_peak, "prefix_cache_hit_rate": hit_rate,
                "gpu_mem_peak_mib": self.gpu_mem_peak}


def run_level(args, model: str, concurrency: int, rng: random.Random, shared_prefix: str) -> dict:
    n = args.requests or max(8, 4 * concurrency)
    prompts = [shared_prefix + synthetic_prompt(rng, args.input_words) for _ in range(n)]
    sampler = ServerSampler(args.metrics_url, args.metrics_interval)
    sampler.start()
    start = time.perf_counter()
    with ThreadPoolExecutor(concurrency) as pool:
        results = list(pool.map(lambda p: stream_one(args.base_url, args.api_key, model, p, args.max_tokens,
                                                     not args.natural_output), prompts))
    wall = time.perf_counter() - start
    server = sampler.finish()
    ok = [r for r in results if r["ok"]]
    out_tokens = sum(r["output_tokens"] for r in ok)
    ttft = [r["ttft_ms"] for r in ok]
    itl = [r["itl_ms"] for r in ok if r["itl_ms"] is not None]
    e2e = [r["e2e_ms"] for r in ok]
    prompt_tokens = [r["prompt_tokens"] for r in ok if r["prompt_tokens"]]
    return {"concurrency": concurrency, "requests": n, "ok": len(ok), "failed": n - len(ok),
            "errors": sorted({r["error"] for r in results if not r["ok"]})[:3],
            "duration_s": round(wall, 2), "requests_per_s": round(len(ok) / wall, 2),
            "output_tokens_per_s": round(out_tokens / wall, 1),
            "mean_prompt_tokens": round(statistics.mean(prompt_tokens)) if prompt_tokens else None,
            "mean_output_tokens": round(out_tokens / len(ok)) if ok else None,
            "ttft_ms": {"p50": pct(ttft, 50), "p95": pct(ttft, 95), "p99": pct(ttft, 99)},
            "itl_ms": {"p50": pct(itl, 50), "p95": pct(itl, 95)},
            "e2e_ms": {"p50": pct(e2e, 50), "p95": pct(e2e, 95)},
            **server}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--model", help="defaults to the first id from /v1/models")
    ap.add_argument("--label", default="run", help="config name used in the report, e.g. qwen7b-fp8")
    ap.add_argument("--concurrency", default="1,4,8,16,32,64")
    ap.add_argument("--requests", type=int, help="requests per level (default max(8, 4 x concurrency))")
    ap.add_argument("--input-words", type=int, default=400, help="unique prompt words per request (~1.3 tokens each)")
    ap.add_argument("--shared-prefix-words", type=int, default=0,
                    help="identical system-prompt-style prefix on every request, to measure prefix caching")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--natural-output", action="store_true", help="let the model stop at EOS instead of ignore_eos")
    ap.add_argument("--metrics-url", help="Prometheus endpoint (default: base URL without /v1 + /metrics)")
    ap.add_argument("--metrics-interval", type=float, default=0.5, help="seconds between /metrics polls")
    ap.add_argument("--no-metrics", action="store_true")
    ap.add_argument("--gpu-price-per-hour", type=float, help="USD per GPU-hour, for cost per 1M output tokens")
    ap.add_argument("--quick", action="store_true", help="concurrency 1,4 with 8 requests each (smoke test)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", help="JSON path (default reports/gpu/<label>.json)")
    args = ap.parse_args(argv)
    args.base_url = args.base_url.rstrip("/")
    if args.quick:
        args.concurrency, args.requests = "1,4", 8
    if args.no_metrics:
        args.metrics_url = None
    elif not args.metrics_url:
        args.metrics_url = args.base_url.removesuffix("/v1") + "/metrics"
    return args


def run(args: argparse.Namespace, extra: dict | None = None) -> dict:
    model = args.model or detect_model(args.base_url, args.api_key)
    rng = random.Random(args.seed)
    shared_prefix = (synthetic_prompt(random.Random(0), args.shared_prefix_words) + "\n\n") if args.shared_prefix_words else ""
    for _ in range(2):
        stream_one(args.base_url, args.api_key, model, "warm up", 8, False)
    levels = []
    print(f"{args.label}: {model} @ {args.base_url}")
    for c in [int(x) for x in args.concurrency.split(",")]:
        lvl = run_level(args, model, c, rng, shared_prefix)
        if args.gpu_price_per_hour and lvl["output_tokens_per_s"]:
            lvl["usd_per_1m_output_tokens"] = round(args.gpu_price_per_hour / (lvl["output_tokens_per_s"] * 3600) * 1e6, 3)
        levels.append(lvl)
        kv = f"kv {lvl['kv_cache_peak_pct']}%" if lvl["kv_cache_peak_pct"] is not None else ""
        print(f"  c={c:<3} {lvl['output_tokens_per_s']:>8} tok/s  ttft p50 {lvl['ttft_ms']['p50']:>7} p95 {lvl['ttft_ms']['p95']:>7} ms  "
              f"itl p50 {lvl['itl_ms']['p50']} ms  e2e p95 {lvl['e2e_ms']['p95']} ms  failed {lvl['failed']}  {kv}")
    result = {"label": args.label, "model": model, "base_url": args.base_url,
              "gpu": gpu_snapshot(), "gpu_price_per_hour": args.gpu_price_per_hour,
              "workload": {"input_words": args.input_words, "shared_prefix_words": args.shared_prefix_words,
                           "max_tokens": args.max_tokens, "fixed_output": not args.natural_output, "seed": args.seed},
              "levels": levels, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **(extra or {})}
    out = Path(args.out) if args.out else ROOT / "reports" / "gpu" / f"{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"  wrote {out}")
    return result


if __name__ == "__main__":
    run(parse_args())
