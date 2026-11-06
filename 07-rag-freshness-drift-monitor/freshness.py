"""Manifests, content hashes and semantic change classification for a knowledge base."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from common.embeddings import cosine, embed

STALE_AFTER_DAYS = 180
CRITICALITY_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")
NEGATION_RE = re.compile(r"\b(not|no longer|never|now|only|removed|deprecated)\b", re.I)


@dataclass
class ChunkEntry:
    chunk_id: str
    doc: str
    heading: str
    text: str
    content_hash: str
    owner: str
    last_reviewed: str
    criticality: str


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse(path: Path) -> list[ChunkEntry]:
    raw = path.read_text()
    meta: dict[str, str] = {}
    if raw.startswith("---"):
        head, raw = raw[3:].split("---", 1)
        meta = dict(line.split(": ", 1) for line in head.strip().splitlines())
    chunks = []
    for block in re.split(r"^## ", raw, flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        text = normalise(body)
        chunks.append(ChunkEntry(
            chunk_id=f"{path.stem}#{heading.strip().lower().replace(' ', '-')}",
            doc=path.stem, heading=heading.strip(), text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest()[:16],
            owner=meta.get("owner", "unowned"), last_reviewed=meta.get("last_reviewed", "1970-01-01"),
            criticality=meta.get("criticality", "low"),
        ))
    return chunks


def build_manifest(kb_dir: Path) -> dict[str, ChunkEntry]:
    return {c.chunk_id: c for p in sorted(kb_dir.glob("*.md")) for c in parse(p)}


def manifest_to_json(manifest: dict[str, ChunkEntry]) -> dict:
    return {k: asdict(v) for k, v in manifest.items()}


@dataclass
class Change:
    chunk_id: str
    kind: str  # added | removed | modified
    severity: str  # cosmetic | minor | material
    semantic_change: float
    numbers_changed: list[str]
    reason: str
    criticality: str
    owner: str


def classify_change(old: str, new: str) -> tuple[str, float, list[str], str]:
    sem = round(1 - cosine(embed(old), embed(new)), 3)
    old_nums, new_nums = NUM_RE.findall(old), NUM_RE.findall(new)
    changed = [f"{a} -> {b}" for a, b in zip(old_nums, new_nums) if a != b]
    flips = set(m.lower() for m in NEGATION_RE.findall(old)) ^ set(m.lower() for m in NEGATION_RE.findall(new))
    if changed:
        return "material", sem, changed, "numeric fact changed"
    if flips:
        return "material", sem, [], f"polarity words changed: {sorted(flips)}"
    if sem >= 0.25:
        return "material", sem, [], "large semantic rewrite"
    if sem >= 0.05:
        return "minor", sem, [], "wording changed"
    return "cosmetic", sem, [], "typo / whitespace only"


def diff(old: dict[str, ChunkEntry], new: dict[str, ChunkEntry]) -> list[Change]:
    changes = []
    for cid in sorted(set(old) | set(new)):
        o, n = old.get(cid), new.get(cid)
        if o and not n:
            changes.append(Change(cid, "removed", "material", 1.0, [], "chunk deleted at source", o.criticality, o.owner))
        elif n and not o:
            changes.append(Change(cid, "added", "material", 1.0, [], "new chunk not yet indexed", n.criticality, n.owner))
        elif o.content_hash != n.content_hash:
            sev, sem, nums, why = classify_change(o.text, n.text)
            changes.append(Change(cid, "modified", sev, sem, nums, why, n.criticality, n.owner))
    return changes


def stale_docs(manifest: dict[str, ChunkEntry], today: date) -> list[tuple[str, str, int]]:
    seen = {}
    for c in manifest.values():
        age = (today - date.fromisoformat(c.last_reviewed)).days
        if age > STALE_AFTER_DAYS:
            seen[c.doc] = (c.doc, c.owner, age)
    return sorted(seen.values(), key=lambda x: -x[2])
