"""Dense + BM25 retrieval, Reciprocal Rank Fusion, and a lightweight rerank pass."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from common.embeddings import cosine, embed
from common.text import content_tokens

CODE_RE = re.compile(r"\b[A-Z]{2,}-\d{3,}\b")


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = {i: Counter(content_tokens(t)) for i, t in docs.items()}
        self.len = {i: sum(c.values()) for i, c in self.tf.items()}
        self.avg = sum(self.len.values()) / max(1, len(self.len))
        df: Counter[str] = Counter()
        for c in self.tf.values():
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        q = content_tokens(query)
        scores = {}
        for i, tf in self.tf.items():
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scores[i] = s
        return sorted(scores.items(), key=lambda x: -x[1])[:k]


def rrf(result_lists: list[list[tuple[str, float]]], weights: list[float], k: int = 60) -> list[tuple[str, float]]:
    fused: dict[str, float] = {}
    for results, w in zip(result_lists, weights):
        for rank, (cid, _) in enumerate(results):
            fused[cid] = fused.get(cid, 0.0) + w / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: -x[1])


@dataclass
class Hit:
    chunk: dict
    dense: float
    rerank: float
    coverage: float


AUTHORITY_PRIOR = {"release_notes": -0.08}
HISTORY_RE = re.compile(r"\b(version|release|changed?|when did|history)\b", re.I)


class Retriever:
    def __init__(
        self,
        index: dict,
        strategy: str = "hybrid",
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        rerank: bool = True,
        pool: int = 8,
    ) -> None:
        self.strategy = strategy
        self.use_rerank = rerank
        self.pool = pool
        self.weights = [dense_weight, sparse_weight]
        self.chunks = {c["id"]: c for c in index["chunks"]}
        self.vectors = index["embeddings"]
        self.bm25 = BM25({cid: f"{c['heading']} {c['text']}" for cid, c in self.chunks.items()})

    def dense(self, query: str, k: int) -> list[tuple[str, float]]:
        qv = embed(query)
        scored = [(cid, cosine(qv, v)) for cid, v in self.vectors.items()]
        return sorted(scored, key=lambda x: -x[1])[:k]

    def search(self, query: str, k: int = 5) -> list[Hit]:
        all_dense = self.dense(query, len(self.vectors))
        if self.strategy == "dense":
            candidates = all_dense[: self.pool]
        elif self.strategy == "sparse":
            candidates = self.bm25.search(query, self.pool)
        else:
            candidates = rrf([all_dense[: self.pool], self.bm25.search(query, self.pool)], self.weights)[: self.pool]
        dense_map = dict(all_dense)
        hits = [self._rerank(query, cid, dense_map.get(cid, 0.0)) for cid, _ in candidates]
        if self.use_rerank:
            hits.sort(key=lambda h: -h.rerank)
        return hits[:k]

    def _rerank(self, query: str, cid: str, dense_score: float) -> Hit:
        c = self.chunks[cid]
        q = set(content_tokens(query))
        body = set(content_tokens(f"{c['heading']} {c['text']}"))
        coverage = len(q & body) / len(q) if q else 0.0
        heading_bonus = 0.15 * len(q & set(content_tokens(c["heading"]))) / max(1, len(q))
        codes = set(CODE_RE.findall(query))
        code_bonus = 0.3 if codes and codes & set(CODE_RE.findall(c["text"])) else 0.0
        prior = 0.0 if HISTORY_RE.search(query) else AUTHORITY_PRIOR.get(c["meta"].get("doc_type", ""), 0.0)
        score = 0.55 * coverage + 0.3 * dense_score + heading_bonus + code_bonus + prior
        return Hit(c, round(dense_score, 4), round(score, 4), round(coverage, 3))
