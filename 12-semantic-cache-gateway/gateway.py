"""Cache-fronted LLM gateway: classify policy -> scoped lookup -> upstream on miss -> store."""

from __future__ import annotations

from dataclasses import dataclass

from cache import SemanticCache, classify
from common.pricing import cost_usd, latency_ms

MODEL = "gpt-4o"
PROMPT_VERSION = "support-v3"
IN_TOKENS, OUT_TOKENS = 650, 160
EXACT_HIT_MS, SEMANTIC_HIT_MS = 3.0, 18.0


@dataclass
class GatewayResult:
    source: str  # exact | semantic | upstream | bypass
    answer: str
    answer_id: str
    cost: float
    latency_ms: float
    similarity: float = 0.0


def upstream(answer_id: str) -> str:
    """Simulated LLM: returns the correct answer for the request's true intent."""
    return f"[answer for {answer_id}]"


class CacheGateway:
    def __init__(self, cache: SemanticCache | None, exact_only: bool = False) -> None:
        self.cache = cache
        self.exact_only = exact_only

    def handle(self, tenant: str, user: str, prompt: str, true_answer_id: str, now: float) -> GatewayResult:
        policy = classify(prompt)
        scope = SemanticCache.scope_key(policy, tenant, user)
        if self.cache is not None:
            hit = self.cache.lookup(prompt, policy, scope, MODEL, PROMPT_VERSION, now)
            if hit.kind == "exact" or (hit.kind == "semantic" and not self.exact_only):
                ms = EXACT_HIT_MS if hit.kind == "exact" else SEMANTIC_HIT_MS
                return GatewayResult(hit.kind, hit.entry.answer, hit.entry.answer_id, 0.0, ms, hit.similarity)
        answer = upstream(true_answer_id)
        cost = cost_usd(MODEL, IN_TOKENS, OUT_TOKENS)
        ms = latency_ms(MODEL, OUT_TOKENS) + (SEMANTIC_HIT_MS if self.cache else 0)
        if self.cache is not None:
            self.cache.store(prompt, policy, scope, MODEL, PROMPT_VERSION, answer, true_answer_id, now)
        return GatewayResult("upstream" if policy.cacheable else "bypass", answer, true_answer_id, cost, ms)
