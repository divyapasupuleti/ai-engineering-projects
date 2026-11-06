"""Grounded answer generation, citation verification, confidence scoring, no-answer handling.

The generator is extractive (selects evidence sentences and cites chunk ids) so it runs
offline and deterministically. In production, replace `draft_answer` with an LLM call that
uses the same contract: answer only from context, cite `[chunk_id]`, say when unknown.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from common.text import content_tokens, overlap_ratio, split_sentences
from retrieval import Hit

CITE_RE = re.compile(r"\[([^\]]+)\]")
CLAIM_RE = re.compile(r"([^\[\]]+?)\s*\[([^\]]+)\]")
MIN_COVERAGE = 0.5
SUPPORT_THRESHOLD = 0.6


@dataclass
class CitationVerdict:
    claim: str
    chunk_id: str
    support: float
    supported: bool


@dataclass
class Answer:
    question: str
    answer: str
    refused: bool
    citations: list[str]
    verdicts: list[CitationVerdict] = field(default_factory=list)
    confidence: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    could_not_verify: list[str] = field(default_factory=list)
    closest_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def draft_answer(question: str, hits: list[Hit], max_sentences: int = 2) -> str:
    q = set(content_tokens(question))
    scored = []
    for rank, hit in enumerate(hits[:3]):
        for sent in split_sentences(hit.chunk["text"]):
            s = set(content_tokens(sent))
            score = len(q & s) / max(1, len(q)) - 0.05 * rank
            scored.append((score, sent, hit.chunk["id"]))
    scored.sort(key=lambda x: -x[0])
    picked = [f"{sent} [{cid}]" for score, sent, cid in scored[:max_sentences] if score > 0]
    return " ".join(picked)


def verify_citations(answer_text: str, chunks: dict[str, dict]) -> list[CitationVerdict]:
    verdicts = []
    for match in CLAIM_RE.finditer(answer_text):
        claim, cid = match.group(1).strip(), match.group(2)
        evidence = chunks.get(cid, {}).get("text", "")
        support = overlap_ratio(claim, evidence)
        verdicts.append(CitationVerdict(claim, cid, round(support, 3), support >= SUPPORT_THRESHOLD))
    return verdicts


def answer_question(question: str, retriever, inject_bad_citation: bool = False) -> Answer:
    hits = retriever.search(question)
    closest = [f"{h.chunk['doc']} > {h.chunk['heading'] or h.chunk['id']}" for h in hits[:3]]
    top_cov = hits[0].coverage if hits else 0.0
    if not hits or top_cov < MIN_COVERAGE:
        return Answer(
            question,
            "I could not find this in the docs. The closest sections are listed below.",
            refused=True,
            citations=[],
            confidence=round(top_cov * 0.5, 3),
            breakdown={"retrieval": round(top_cov, 3)},
            closest_sections=closest,
        )

    text = draft_answer(question, hits)
    if inject_bad_citation and len(hits) > 1:
        wrong = next(h.chunk["id"] for h in reversed(hits) if h.chunk["id"] not in text)
        text = CITE_RE.sub(f"[{wrong}]", text, count=1)

    verdicts = verify_citations(text, retriever.chunks)
    support_rate = sum(v.supported for v in verdicts) / len(verdicts) if verdicts else 0.0
    completeness = overlap_ratio(question, CITE_RE.sub("", text))
    retrieval_score = min(1.0, hits[0].rerank)
    confidence = 0.35 * retrieval_score + 0.45 * support_rate + 0.2 * completeness
    return Answer(
        question,
        text,
        refused=False,
        citations=sorted({v.chunk_id for v in verdicts}),
        verdicts=verdicts,
        confidence=round(confidence, 3),
        breakdown={
            "retrieval": round(retrieval_score, 3),
            "citation_support_rate": round(support_rate, 3),
            "completeness": round(completeness, 3),
        },
        could_not_verify=[v.claim for v in verdicts if not v.supported],
        closest_sections=closest,
    )
