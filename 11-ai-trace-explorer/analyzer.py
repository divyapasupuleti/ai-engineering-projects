"""Classify each trace's failure, point at the root-cause span and suggest a fix."""

from __future__ import annotations

from dataclasses import dataclass

SLO_MS = {"rerank": 300, "retrieve": 200, "tool.lookup_order": 400, "request": 8000}
HINTS = {
    "llm_timeout": ("provider", "Set a per-call timeout budget and fail over to a second model (gateway routing)."),
    "rate_limited": ("platform", "Rate limited on every retry: raise quota, add a queue, or spread load across providers."),
    "rate_limited_recovered": ("platform", "Recovered after 429 retries; latency cost of backoff is visible in the waterfall."),
    "context_overflow": ("rag", "Retrieved context exceeds the model window: lower k, trim chunks or summarise before generation."),
    "retrieval_empty": ("rag", "No documents retrieved: check query rewriting and index freshness before blaming the model."),
    "tool_error": ("integrations", "Downstream API failed: add a circuit breaker and a graceful 'cannot check order' answer."),
    "schema_invalid": ("prompt", "Output was not valid JSON: use structured output / JSON mode; compare prompt versions."),
    "ungrounded": ("quality", "Answer has low grounding and no citations: enforce citations via the output guardrail."),
    "latency_slo": ("performance", "Span exceeded its latency SLO: profile this dependency or cache its results."),
}
SEVERITY = {"llm_timeout": 3, "rate_limited": 3, "context_overflow": 3, "tool_error": 3, "schema_invalid": 3,
            "retrieval_empty": 2, "ungrounded": 2, "latency_slo": 1, "rate_limited_recovered": 1}


@dataclass
class Finding:
    category: str
    span: str
    detail: str
    start_ms: float

    @property
    def owner(self) -> str:
        return HINTS[self.category][0]

    @property
    def hint(self) -> str:
        return HINTS[self.category][1]


def analyse(spans: list[dict]) -> list[Finding]:
    f: list[Finding] = []
    llm = [s for s in spans if s["name"] == "llm.generate"]
    for s in spans:
        err = s["error"] or ""
        if "timeout" in err:
            f.append(Finding("llm_timeout", s["name"], err, s["start_ms"]))
        elif "context length" in err:
            f.append(Finding("context_overflow", s["name"], err, s["start_ms"]))
        elif s["name"].startswith("tool.") and s["status"] == "error":
            f.append(Finding("tool_error", s["name"], err, s["start_ms"]))
        elif s["name"] == "validate.output" and s["status"] == "error":
            f.append(Finding("schema_invalid", s["name"], err, s["start_ms"]))
        if s["name"] == "retrieve" and s["attrs"].get("hits") == 0:
            f.append(Finding("retrieval_empty", s["name"], "0 hits", s["start_ms"]))
        if s["name"] == "llm.generate" and s["attrs"].get("grounding", 1) < 0.5:
            f.append(Finding("ungrounded", s["name"], f"grounding={s['attrs']['grounding']}", s["start_ms"]))
        slo = SLO_MS.get(s["name"])
        if slo and s["duration_ms"] > slo and s["name"] != "request":
            f.append(Finding("latency_slo", s["name"], f"{s['duration_ms']:.0f} ms > {slo} ms SLO", s["start_ms"]))
    limited = [s for s in llm if "429" in (s["error"] or "")]
    if limited:
        recovered = any(s["status"] == "ok" for s in llm)
        f.append(Finding("rate_limited_recovered" if recovered else "rate_limited", "llm.generate",
                         f"{len(limited)} x HTTP 429", limited[0]["start_ms"]))
    return sorted(f, key=lambda x: (-SEVERITY[x.category], x.start_ms))


def root_cause(findings: list[Finding]) -> Finding | None:
    return findings[0] if findings else None


def self_time(spans: list[dict]) -> dict[str, float]:
    """Duration minus children: tells you which step actually consumed the time."""
    children: dict[str, float] = {}
    for s in spans:
        if s["parent_id"]:
            children[s["parent_id"]] = children.get(s["parent_id"], 0) + s["duration_ms"]
    out: dict[str, float] = {}
    for s in spans:
        out[s["name"]] = out.get(s["name"], 0) + max(0.0, s["duration_ms"] - children.get(s["span_id"], 0))
    return out
