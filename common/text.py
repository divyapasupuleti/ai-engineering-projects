"""Tokenisation helpers shared by retrieval, caching, and eval code."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a an and are as at be by can do does for from has have how i if in is it its
    me my of on or our please should that the their there this to was we what when
    where which who why will with you your about after before into than then them
    they would could also any all get got just not no yes""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def content_tokens(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS]


def count_tokens(text: str) -> int:
    """Rough tokenizer-free estimate (~4 chars per token), good enough for cost math."""
    return max(1, round(len(text) / 4))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text.strip()) if s.strip()]


def overlap_ratio(claim: str, evidence: str) -> float:
    """Share of the claim's content tokens that also appear in the evidence."""
    c = set(content_tokens(claim))
    if not c:
        return 0.0
    return len(c & set(content_tokens(evidence))) / len(c)
