"""A traced multi-step support workflow with seeded fault injection.

guard -> retrieve -> rerank -> llm.generate (with retry) -> tool.lookup_order (optional) -> validate
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

from trace_store import SimClock, TraceRecorder

QUESTIONS = [
    ("support_bot", "Where is my order 4411?", True),
    ("support_bot", "How do I reset my password?", False),
    ("support_bot", "Can I get a refund for a double charge?", False),
    ("support_bot", "Order 9902 arrived damaged, what now?", True),
    ("support_bot", "Is SSO available on the Pro plan?", False),
    ("support_bot", "Why is my export stuck?", False),
]
FAULTS = {
    "none": 0.62, "retrieval_empty": 0.06, "llm_timeout": 0.05, "rate_limited": 0.07, "tool_error": 0.05,
    "schema_invalid": 0.05, "ungrounded": 0.05, "slow_rerank": 0.03, "context_overflow": 0.02,
}
MAX_CONTEXT = 8000


class StepError(Exception):
    pass


@dataclass
class RunResult:
    recorder: TraceRecorder
    meta: dict
    injected: str


def run_once(rng: random.Random, clock: SimClock, prompt_version: str = "support-v7", model: str = "gpt-4o-mini") -> RunResult:
    feature, question, needs_tool = rng.choice(QUESTIONS)
    fault = rng.choices(list(FAULTS), list(FAULTS.values()))[0]
    if prompt_version == "support-v8" and fault == "none" and rng.random() < 0.15:
        fault = "schema_invalid"
    rec = TraceRecorder(clock)
    meta = {"feature": feature, "prompt_version": prompt_version, "model": model, "user_input": question}
    try:
        with rec.span("request", feature=feature, prompt_version=prompt_version, injected_fault=fault):
            with rec.span("guard.input", chars=len(question)):
                clock.advance(rng.uniform(3, 8))
            with rec.span("retrieve", index="kb-2026-10", k=8) as s:
                clock.advance(rng.uniform(40, 90))
                hits = 0 if fault == "retrieval_empty" else rng.randint(4, 8)
                s.attrs["hits"] = hits
                s.attrs["top_score"] = 0.0 if hits == 0 else round(rng.uniform(0.55, 0.9), 2)
            with rec.span("rerank", model="bge-reranker", candidates=hits) as s:
                clock.advance(rng.uniform(900, 1600) if fault == "slow_rerank" else rng.uniform(25, 60))
            ctx_tokens = rng.randint(6000, 9000) if fault == "context_overflow" else rng.randint(900, 2400)
            answer = None
            for attempt in range(1, 4):
                with rec.span("llm.generate", model=model, attempt=attempt, input_tokens=ctx_tokens) as s:
                    if fault == "context_overflow" and ctx_tokens > MAX_CONTEXT:
                        clock.advance(30)
                        raise StepError(f"context length {ctx_tokens} exceeds {MAX_CONTEXT}")
                    if fault == "llm_timeout":
                        clock.advance(30000)
                        raise StepError("provider timeout after 30000 ms")
                    if fault == "rate_limited" and attempt < 3 and rng.random() < 0.8:
                        clock.advance(rng.uniform(80, 150))
                        s.status, s.error = "error", "HTTP 429 rate limited"
                        s.attrs["retry_after_ms"] = 500 * attempt
                        clock.advance(500 * attempt)
                        continue
                    out_tokens = rng.randint(80, 260)
                    clock.advance(350 + 8 * out_tokens)
                    s.attrs["output_tokens"] = out_tokens
                    grounding = round(rng.uniform(0.15, 0.4) if fault == "ungrounded" else rng.uniform(0.7, 0.98), 2)
                    s.attrs["grounding"] = grounding
                    body = {"answer": f"Answer to: {question}", "citations": [] if fault == "ungrounded" else ["kb#1"]}
                    answer = "{answer: " + body["answer"] if fault == "schema_invalid" else json.dumps(body)
                    break
            if answer is None:
                raise StepError("rate limited on all attempts")
            if needs_tool:
                with rec.span("tool.lookup_order", tool="orders_api") as s:
                    clock.advance(rng.uniform(60, 140))
                    if fault == "tool_error":
                        s.attrs["http_status"] = 503
                        raise StepError("orders_api returned 503")
                    s.attrs["http_status"] = 200
            with rec.span("validate.output") as s:
                clock.advance(rng.uniform(2, 6))
                try:
                    parsed = json.loads(answer)
                except json.JSONDecodeError as exc:
                    raise StepError(f"output is not valid JSON: {exc.msg}") from exc
                s.attrs["citations"] = len(parsed["citations"])
            meta["output"] = answer
    except StepError:
        pass
    return RunResult(rec, meta, fault)
