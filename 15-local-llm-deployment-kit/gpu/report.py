#!/usr/bin/env python3
"""Turn reports/gpu/*.json into GPU_BENCHMARK.md (+ charts when matplotlib is installed).

    python3 gpu/report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DIR = HERE.parent / "reports" / "gpu"
DEFAULT_SLO = {"ttft_p95_ms": 1000, "itl_p50_ms": 50}


def load_results(out_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(out_dir.glob("*.json"))]


def meets_slo(level: dict, slo: dict) -> bool:
    ttft, itl = level["ttft_ms"]["p95"], level["itl_ms"]["p50"]
    return (level["failed"] == 0 and ttft is not None and ttft <= slo["ttft_p95_ms"]
            and (itl is None or itl <= slo["itl_p50_ms"]))


def summarise(result: dict, slo: dict) -> dict:
    levels = result["levels"]
    single = next((lv for lv in levels if lv["concurrency"] == 1), levels[0])
    peak = max(levels, key=lambda lv: lv["output_tokens_per_s"])
    within = [lv for lv in levels if meets_slo(lv, slo)]
    best = max(within, key=lambda lv: lv["output_tokens_per_s"]) if within else None
    itl1 = single["itl_ms"]["p50"]
    return {"label": result["label"], "description": (result.get("config") or {}).get("description", ""),
            "group": (result.get("config") or {}).get("group"),
            "single_stream_tok_s": round(1000 / itl1, 1) if itl1 else None,
            "ttft_p50_c1_ms": single["ttft_ms"]["p50"],
            "peak_tok_s": peak["output_tokens_per_s"], "peak_at": peak["concurrency"],
            "slo_users": best["concurrency"] if best else 0,
            "slo_tok_s": best["output_tokens_per_s"] if best else None,
            "slo_usd_per_1m": best.get("usd_per_1m_output_tokens") if best else None,
            "gpu_mem_peak_gib": round(max((lv["gpu_mem_peak_mib"] or 0) for lv in levels) / 1024, 1) or None,
            "kv_peak_pct": max((lv["kv_cache_peak_pct"] or 0) for lv in levels) or None}


def fmt(v, suffix: str = "", digits: int = 1) -> str:
    if v is None:
        return "–"
    if isinstance(v, int):
        return f"{v:,}{suffix}"
    return f"{v:,.{digits}f}{suffix}" if isinstance(v, float) else f"{v}{suffix}"


def charts(results: list[dict], out_dir: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    made = []
    for key, title, fname, getter in [
        ("tput", "Output throughput vs concurrent users", "throughput_vs_concurrency.png", lambda lv: lv["output_tokens_per_s"]),
        ("ttft", "Time to first token (p95) vs concurrent users", "ttft_p95_vs_concurrency.png", lambda lv: lv["ttft_ms"]["p95"]),
    ]:
        fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
        for r in results:
            xs = [lv["concurrency"] for lv in r["levels"]]
            ax.plot(xs, [getter(lv) for lv in r["levels"]], marker="o", label=r["label"])
        ax.set_xscale("log", base=2)
        ax.set_xlabel("concurrent streams")
        ax.set_ylabel("output tokens/s" if key == "tput" else "ms")
        if key == "ttft":
            slo = (results[0].get("slo") or DEFAULT_SLO)["ttft_p95_ms"]
            ax.axhline(slo, color="grey", linestyle="--", linewidth=1)
            ax.text(ax.get_xlim()[0], slo, f" SLO {slo} ms", va="bottom", fontsize=8, color="grey")
        ax.set_title(title)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / fname)
        plt.close(fig)
        made.append(fname)
    return made


def cv_bullets(summaries: list[dict], prefix_pair: tuple[dict, dict] | None, gpu: str, model: str) -> list[str]:
    bullets = []
    ranked = [s for s in summaries if s["group"] != "prefix-caching" and s["slo_tok_s"]]
    if ranked:
        best = max(ranked, key=lambda s: s["slo_tok_s"])
        base = next((s for s in ranked if "bf16" in s["label"]), None)
        line = (f"Benchmarked {model} on vLLM ({gpu}): {best['label']} sustained {best['slo_tok_s']:,.0f} output tokens/s "
                f"for {best['slo_users']} concurrent users within a 1 s p95 time-to-first-token SLO")
        if base and base is not best and base["slo_tok_s"]:
            line += f", {best['slo_tok_s'] / base['slo_tok_s']:.1f}x the BF16 baseline"
        if best["slo_usd_per_1m"]:
            line += f", at ${best['slo_usd_per_1m']:.3f} per 1M output tokens"
        bullets.append(line + ".")
    if prefix_pair:
        on, off = prefix_pair
        if on["ttft"] and off["ttft"]:
            cut = 100 * (1 - on["ttft"] / off["ttft"])
            bullets.append(f"Measured automatic prefix caching on a 2k-token shared system prompt: p95 time-to-first-token "
                           f"{off['ttft']:,.0f} ms -> {on['ttft']:,.0f} ms ({cut:.0f}% lower) at {on['c']} concurrent users"
                           + (f", {on['hit']:.0%} cache hit rate." if on.get("hit") else "."))
    return bullets


def build(out_dir: Path = DEFAULT_DIR) -> str:
    results = [r for r in load_results(out_dir) if "levels" in r]
    if not results:
        return f"no results in {out_dir}"
    slo = results[0].get("slo") or DEFAULT_SLO
    gpu = next((f"{r['gpu']['name']}" + (f" x{r['gpu']['count']}" if r["gpu"]["count"] > 1 else "")
                for r in results if r.get("gpu")), results[0].get("gpu_type_requested", "unknown GPU"))
    model = results[0]["model"].split("/")[-1].removesuffix("-AWQ")
    version = next((r["vllm_version"] for r in results if r.get("vllm_version")), "unknown")
    summaries = [summarise(r, slo) for r in results]
    images = charts(results, out_dir)

    lines = [f"# GPU inference benchmark: {model} on vLLM", "",
             f"- **GPU:** {gpu} · **vLLM:** {version} · **run:** {results[0]['timestamp']}",
             f"- **Workload:** {results[0]['workload']['input_words']} prompt words, "
             f"{results[0]['workload']['max_tokens']} output tokens per request, streaming",
             f"- **SLO:** p95 time to first token ≤ {slo['ttft_p95_ms']} ms and median inter-token latency ≤ {slo['itl_p50_ms']} ms "
             f"(≥ {1000 // slo['itl_p50_ms']} tokens/s per user)", "",
             "## Summary", "",
             "| Config | Single-user tok/s | TTFT p50 (1 user) | Peak tok/s | Users within SLO | tok/s within SLO | $ per 1M tokens | GPU mem peak | KV cache peak |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in summaries:
        lines.append(f"| `{s['label']}` | {fmt(s['single_stream_tok_s'])} | {fmt(s['ttft_p50_c1_ms'], ' ms')} | "
                     f"{fmt(s['peak_tok_s'])} (c={s['peak_at']}) | {s['slo_users']} | {fmt(s['slo_tok_s'])} | "
                     f"{fmt(s['slo_usd_per_1m'], digits=3)} | {fmt(s['gpu_mem_peak_gib'], ' GiB')} | {fmt(s['kv_peak_pct'], '%')} |")
    ranked = [s for s in summaries if s["group"] != "prefix-caching" and s["slo_tok_s"]]
    if ranked:
        best = max(ranked, key=lambda s: s["slo_tok_s"])
        lines += ["", f"**Recommendation:** `{best['label']}`: the most throughput ({best['slo_tok_s']:,.0f} tok/s, "
                      f"{best['slo_users']} concurrent users) while meeting the SLO. Check output quality on your eval set "
                      f"before switching precision in production."]
    if images:
        lines += ["", "## Charts", ""] + [f"![{i}]({i})" for i in images]

    prefix_pair = None
    on = next((r for r in results if r["label"].endswith("prefix-cache-on")), None)
    off = next((r for r in results if r["label"].endswith("prefix-cache-off")), None)
    if on and off:
        lines += ["", "## Prefix caching (shared ~2k-token system prompt)", "",
                  "| Users | TTFT p95 off | TTFT p95 on | tok/s off | tok/s on | Cache hit rate |", "|---|---|---|---|---|---|"]
        for a, b in zip(off["levels"], on["levels"]):
            lines.append(f"| {a['concurrency']} | {fmt(a['ttft_ms']['p95'], ' ms')} | {fmt(b['ttft_ms']['p95'], ' ms')} | "
                         f"{fmt(a['output_tokens_per_s'])} | {fmt(b['output_tokens_per_s'])} | "
                         f"{fmt(b['prefix_cache_hit_rate'] and round(100 * b['prefix_cache_hit_rate'], 1), '%')} |")
        a, b = off["levels"][-1], on["levels"][-1]
        prefix_pair = ({"ttft": b["ttft_ms"]["p95"], "c": b["concurrency"], "hit": b["prefix_cache_hit_rate"]},
                       {"ttft": a["ttft_ms"]["p95"]})

    lines += ["", "## Detail per concurrency level", ""]
    for r in results:
        lines += [f"### `{r['label']}`", (r.get("config") or {}).get("description", ""), "",
                  "| Users | Requests | tok/s | req/s | TTFT p50 / p95 / p99 ms | ITL p50 / p95 ms | E2E p95 ms | Queued peak | Failed |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for lv in r["levels"]:
            t, i = lv["ttft_ms"], lv["itl_ms"]
            lines.append(f"| {lv['concurrency']} | {lv['requests']} | {fmt(lv['output_tokens_per_s'])} | {fmt(lv['requests_per_s'])} | "
                         f"{fmt(t['p50'])} / {fmt(t['p95'])} / {fmt(t['p99'])} | {fmt(i['p50'])} / {fmt(i['p95'])} | "
                         f"{fmt(lv['e2e_ms']['p95'])} | {fmt(lv['queued_peak'])} | {lv['failed']} |")
        lines.append("")

    bullets = cv_bullets(summaries, prefix_pair, gpu, model)
    if bullets:
        lines += ["## CV / LinkedIn lines (generated from these numbers)", ""] + [f"- {b}" for b in bullets]
    (out_dir / "GPU_BENCHMARK.md").write_text("\n".join(lines) + "\n")
    return f"wrote {out_dir / 'GPU_BENCHMARK.md'}" + (f" and {', '.join(images)}" if images else "")


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR))
