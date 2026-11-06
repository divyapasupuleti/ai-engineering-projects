#!/usr/bin/env python3
"""Benchmark quantisation profiles under concurrency, pick one for the hardware/SLO, and exercise ops paths.

    python benchmark.py                 # simulator, time compressed 50x
    python benchmark.py --ollama        # real Ollama models (slow; pull the tags in config/models.json first)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

KEY = "local-dev-key"
CONCURRENCY = [1, 4, 8, 16]


def call(port: int, path: str, body: dict | None = None, method: str = "POST") -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data, method=method,
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def load_test(port: int, concurrency: int, requests: int, scale: float) -> dict:
    def one(i: int):
        return call(port, "/v1/chat/completions", {"model": "active", "max_tokens": 64,
                                                   "messages": [{"role": "user", "content": f"Summarise ticket {i} about export failures in two lines"}]})
    start = time.perf_counter()
    with ThreadPoolExecutor(concurrency) as pool:
        results = list(pool.map(one, range(requests)))
    wall = (time.perf_counter() - start) / scale
    ok = [r for s, r in results if s == 200]
    lat = sorted(r["x_timing"]["total_ms"] for r in ok)
    tokens = sum(r["usage"]["completion_tokens"] for r in ok)
    pct = lambda p: lat[min(len(lat) - 1, int(p / 100 * len(lat)))] if lat else float("nan")  # noqa: E731
    return {"concurrency": concurrency, "ok": len(ok), "rejected_429": sum(1 for s, _ in results if s == 429),
            "p50_ms": round(pct(50)), "p95_ms": round(pct(95)), "ttft_p50_ms": round(sorted(r["x_timing"]["ttft_ms"] for r in ok)[len(ok) // 2]) if ok else None,
            "tokens_per_s": round(tokens / wall, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ollama", action="store_true")
    ap.add_argument("--port", type=int, default=8815)
    args = ap.parse_args()
    if not args.ollama:
        os.environ.setdefault("SIM_TIME_SCALE", "0.02")
    from llm_server import build_server  # noqa: E402  (reads SIM_TIME_SCALE at import)
    import backends

    scale = backends.TIME_SCALE
    srv, mgr, _ = build_server(args.port, prefer_ollama=args.ollama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hw = mgr.cfg["hardware"]
    print(f"Hardware: {hw['name']} · memory budget {hw['memory_budget_gb']} GB · SLO p95 {hw['slo_p95_ms']} ms · "
          f"backend {type(mgr.backend).__name__}{' (time x' + str(scale) + ')' if scale != 1 else ''}\n")

    report = {}
    for name, prof in mgr.cfg["profiles"].items():
        if prof.get("fail"):
            continue
        ok, msg = mgr.switch(name) if name != mgr.active else (True, "")
        if not ok:
            print(f"{name:<20} SKIPPED: {msg}")
            report[name] = {"skipped": msg}
            continue
        rows = [load_test(args.port, c, max(8, 3 * c), scale) for c in CONCURRENCY]
        report[name] = {"memory_gb": prof["memory_gb"], "quality": prof["quality"], "runs": rows}
        print(f"{name:<20} mem {prof['memory_gb']:>4} GB · quality {prof['quality']:.2f}")
        for r in rows:
            print(f"   c={r['concurrency']:<3} p50 {r['p50_ms']:>6} ms  p95 {r['p95_ms']:>6} ms  ttft {r['ttft_p50_ms']:>5} ms  "
                  f"{r['tokens_per_s']:>6} tok/s  429s {r['rejected_429']}")

    def meets(name: str) -> bool:
        r8 = next(r for r in report[name]["runs"] if r["concurrency"] == 8)
        return r8["p95_ms"] <= hw["slo_p95_ms"] and r8["rejected_429"] == 0

    eligible = [n for n, v in report.items() if "runs" in v and meets(n)]
    best = max(eligible, key=lambda n: report[n]["quality"]) if eligible else None
    print(f"\nRecommendation: {best} (highest quality meeting p95 <= {hw['slo_p95_ms']} ms at 8 concurrent with no 429s)")

    print("\nOps checks:")
    mgr.switch(best)
    s, r = call(args.port, "/admin/switch", {"model": "broken-model:q4"})
    print(f"  switch to broken-model -> HTTP {s}: {r['message']}")
    s, r = call(args.port, "/admin/switch", {"model": "llama3.1-8b:fp16"})
    print(f"  switch to fp16 -> HTTP {s}: {r['message']}")
    s, r = call(args.port, "/admin/switch", {"model": "qwen2.5-3b:q4_K_M"})
    print(f"  switch to qwen2.5-3b -> HTTP {s}: {r['message']}")
    s, r = call(args.port, "/admin/rollback", {})
    print(f"  rollback -> HTTP {s}: {r['message']}")
    req = urllib.request.Request(f"http://127.0.0.1:{args.port}/v1/chat/completions",
                                 json.dumps({"stream": True, "max_tokens": 8, "messages": [{"role": "user", "content": "hello"}]}).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    chunks = [line for line in urllib.request.urlopen(req, timeout=30).read().decode().splitlines() if line.startswith("data:")]
    print(f"  streaming -> {len(chunks) - 1} SSE chunks + [DONE]={chunks[-1] == 'data: [DONE]'}")
    bad = urllib.request.Request(f"http://127.0.0.1:{args.port}/v1/chat/completions", b"{}", headers={"Authorization": "Bearer wrong"})
    try:
        urllib.request.urlopen(bad, timeout=5)
    except urllib.error.HTTPError as e:
        print(f"  wrong API key -> HTTP {e.code}")
    metrics = urllib.request.urlopen(f"http://127.0.0.1:{args.port}/metrics", timeout=5).read().decode().splitlines()
    shown = [m for m in metrics if m.startswith(("llm_requests_total", "llm_active_model_info"))][:6]
    print("  /metrics sample:\n    " + "\n    ".join(shown))

    out = ROOT / "reports" / "benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"hardware": hw, "time_scale": scale, "results": report, "recommendation": best}, indent=2))
    print(f"\nWrote {out.relative_to(ROOT)}")
    srv.shutdown()


if __name__ == "__main__":
    main()
