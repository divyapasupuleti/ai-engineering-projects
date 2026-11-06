"""A tiny vector index plus retrieval-drift and answer-drift probes."""

from __future__ import annotations

from dataclasses import dataclass

from common.embeddings import cosine, embed
from common.text import content_tokens, overlap_ratio, split_sentences
from freshness import ChunkEntry


class VectorIndex:
    """Stores one embedding per chunk, keyed by content hash so unchanged chunks are never re-embedded."""

    def __init__(self) -> None:
        self.entries: dict[str, ChunkEntry] = {}
        self.vectors: dict[str, list[float]] = {}
        self.embed_calls = 0

    def upsert(self, chunk: ChunkEntry) -> None:
        cached = self.entries.get(chunk.chunk_id)
        if cached and cached.content_hash == chunk.content_hash:
            self.entries[chunk.chunk_id] = chunk
            return
        self.vectors[chunk.chunk_id] = embed(f"{chunk.heading}. {chunk.text}")
        self.entries[chunk.chunk_id] = chunk
        self.embed_calls += 1

    def delete(self, chunk_id: str) -> None:
        self.entries.pop(chunk_id, None)
        self.vectors.pop(chunk_id, None)

    def search(self, query: str, k: int = 3) -> list[tuple[ChunkEntry, float]]:
        q = embed(query)
        qt = set(content_tokens(query))
        scored = []
        for cid, vec in self.vectors.items():
            c = self.entries[cid]
            lexical = len(qt & set(content_tokens(f"{c.heading} {c.text}"))) / max(1, len(qt))
            scored.append((c, round(0.6 * cosine(q, vec) + 0.4 * lexical, 4)))
        return sorted(scored, key=lambda x: -x[1])[:k]

    def clone(self) -> "VectorIndex":
        other = VectorIndex()
        other.entries, other.vectors = dict(self.entries), dict(self.vectors)
        return other


def answer(index: VectorIndex, question: str) -> tuple[str, str, float]:
    hits = index.search(question, k=1)
    if not hits:
        return "", "", 0.0
    chunk, score = hits[0]
    best = max(split_sentences(chunk.text), key=lambda s: overlap_ratio(question, s))
    return best, chunk.chunk_id, score


@dataclass
class ProbeResult:
    probe_id: str
    question: str
    traffic: int
    old_chunk: str
    new_chunk: str
    old_score: float
    new_score: float
    old_answer: str
    new_answer: str
    fact: str

    @property
    def retrieval_drift(self) -> bool:
        return self.old_chunk != self.new_chunk or abs(self.new_score - self.old_score) > 0.08

    @property
    def answer_drift(self) -> bool:
        return self.old_answer != self.new_answer

    @property
    def deployed_stale(self) -> bool:
        return self.fact.lower() not in self.old_answer.lower()

    @property
    def candidate_correct(self) -> bool:
        return self.fact.lower() in self.new_answer.lower()


def run_probes(deployed: VectorIndex, candidate: VectorIndex, probes: list[dict]) -> list[ProbeResult]:
    out = []
    for p in probes:
        oa, oc, os_ = answer(deployed, p["question"])
        na, nc, ns = answer(candidate, p["question"])
        out.append(ProbeResult(p["id"], p["question"], p["traffic"], oc, nc, os_, ns, oa, na, p["fact_v2"]))
    return out
