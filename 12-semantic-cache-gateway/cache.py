"""Two-tier LLM response cache: exact hash, then semantic similarity with safety validation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from common.embeddings import embed

ENTITY_VOCAB = {"starter", "pro", "enterprise", "january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december", "ios", "android", "csv", "parquet"}
NEGATIONS = {"not", "no", "never", "dont", "don't", "cannot", "can't", "without"}
NUM_RE = re.compile(r"\d+")
WORD_RE = re.compile(r"[a-z']+")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


def signature(text: str) -> tuple[frozenset, frozenset, bool]:
    """Things that must match exactly for two prompts to share an answer."""
    words = set(WORD_RE.findall(text.lower()))
    return frozenset(NUM_RE.findall(text)), frozenset(words & ENTITY_VOCAB), bool(words & NEGATIONS)


@dataclass
class Policy:
    cacheable: bool
    scope: str  # global | tenant | user
    tag: str
    ttl_s: int


def classify(prompt: str) -> Policy:
    p = prompt.lower()
    if re.search(r"\d{4,}|\bstatus of\b|\bright now\b|\btoday\b", p):
        return Policy(False, "user", "realtime", 0)
    personal = re.search(r"\b(my|our|we|us|mine)\b", p) and not re.search(r"\bmy password\b", p)
    if personal or re.search(r"invoice|seats?\b|usage|account|\bbill", p):
        return Policy(True, "tenant", "account", 3600)
    if re.search(r"\b(price|cost|pricing|discount|how much|starter|pro|enterprise)\b", p):
        return Policy(True, "global", "pricing", 24 * 3600)
    return Policy(True, "global", "docs", 7 * 24 * 3600)


@dataclass
class Entry:
    key: str
    prompt: str
    vec: list[float]
    answer: str
    answer_id: str
    scope_key: str
    tag: str
    expires_at: float
    hits: int = 0
    prompt_version: str = ""


@dataclass
class Lookup:
    kind: str  # exact | semantic | miss | bypass
    entry: Entry | None = None
    similarity: float = 0.0
    rejected_reason: str | None = None


@dataclass
class SemanticCache:
    threshold: float = 0.86
    near_miss_band: float = 0.06
    validate: bool = True
    exact: dict[str, Entry] = field(default_factory=dict)
    buckets: dict[str, list[Entry]] = field(default_factory=dict)
    near_misses: list[dict] = field(default_factory=list)

    @property
    def entries(self) -> list[Entry]:
        return [e for b in self.buckets.values() for e in b]

    @staticmethod
    def scope_key(policy: Policy, tenant: str, user: str) -> str:
        return {"global": "global", "tenant": f"t:{tenant}", "user": f"u:{tenant}:{user}"}[policy.scope]

    def key(self, prompt: str, scope: str, model: str, prompt_version: str) -> str:
        return hashlib.sha256(f"{scope}|{model}|{prompt_version}|{normalise(prompt)}".encode()).hexdigest()[:20]

    def lookup(self, prompt: str, policy: Policy, scope: str, model: str, prompt_version: str, now: float) -> Lookup:
        if not policy.cacheable:
            return Lookup("bypass")
        k = self.key(prompt, scope, model, prompt_version)
        e = self.exact.get(k)
        if e and e.expires_at > now:
            e.hits += 1
            return Lookup("exact", e, 1.0)
        q = sparse(embed(normalise(prompt)))
        sig = signature(prompt)
        best, best_sim = None, 0.0
        for cand in self.buckets.get(scope, []):
            if cand.expires_at <= now or cand.prompt_version != prompt_version:
                continue
            sim = sdot(q, cand.vec)
            if sim > best_sim:
                best, best_sim = cand, sim
        if best is None:
            return Lookup("miss")
        if best_sim < self.threshold:
            if best_sim >= self.threshold - self.near_miss_band:
                self.near_misses.append({"prompt": prompt, "cached": best.prompt, "sim": round(best_sim, 3), "why": "below threshold"})
            return Lookup("miss", similarity=best_sim)
        if self.validate and signature(best.prompt) != sig:
            self.near_misses.append({"prompt": prompt, "cached": best.prompt, "sim": round(best_sim, 3), "why": "entity/number/negation mismatch"})
            return Lookup("miss", similarity=best_sim, rejected_reason="signature mismatch")
        best.hits += 1
        return Lookup("semantic", best, best_sim)

    def store(self, prompt: str, policy: Policy, scope: str, model: str, prompt_version: str,
              answer: str, answer_id: str, now: float) -> None:
        if not policy.cacheable:
            return
        k = self.key(prompt, scope, model, prompt_version)
        e = Entry(k, prompt, sparse(embed(normalise(prompt))), answer, answer_id, scope, policy.tag,
                  now + policy.ttl_s, prompt_version=prompt_version)
        bucket = self.buckets.setdefault(scope, [])
        if k in self.exact:
            bucket[:] = [x for x in bucket if x.key != k]
        self.exact[k] = e
        bucket.append(e)

    def _filter(self, keep) -> int:
        before = len(self.exact)
        for scope, bucket in self.buckets.items():
            self.buckets[scope] = [e for e in bucket if keep(e)]
        self.exact = {k: e for k, e in self.exact.items() if keep(e)}
        return before - len(self.exact)

    def invalidate_tag(self, tag: str) -> int:
        return self._filter(lambda e: e.tag != tag)

    def evict_expired(self, now: float) -> int:
        return self._filter(lambda e: e.expires_at > now)


def sparse(vec: list[float]) -> dict[int, float]:
    return {i: v for i, v in enumerate(vec) if v}


def sdot(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(i, 0.0) for i, v in a.items())
