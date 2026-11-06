#!/usr/bin/env python3
"""Load Markdown docs, chunk them, and build dense + sparse indexes over shared chunk ids.

    python ingest.py --source data/docs --strategy heading --rebuild
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from common.embeddings import embed  # noqa: E402
from common.io import read_json, write_json  # noqa: E402

INDEX_PATH = ROOT / ".index" / "index.json"


@dataclass
class Chunk:
    id: str
    doc: str
    heading: str
    text: str
    strategy: str
    meta: dict[str, str] = field(default_factory=dict)


def parse_doc(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if raw.startswith("---"):
        _, front, body = raw.split("---", 2)
        for line in front.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        return meta, body.strip()
    return meta, raw.strip()


def chunk_by_heading(doc_id: str, meta: dict[str, str], body: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading, lines = "", []

    def flush() -> None:
        text = " ".join(l.strip() for l in lines if l.strip())
        if text:
            chunks.append(Chunk(f"{doc_id}#{len(chunks)}", doc_id, heading, text, "heading", meta))

    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            heading, lines = line[3:].strip(), []
        elif not line.startswith("# "):
            lines.append(line)
    flush()
    return chunks


def chunk_fixed(doc_id: str, meta: dict[str, str], body: str, size: int = 45, overlap: int = 10) -> list[Chunk]:
    words = [w for w in body.replace("#", " ").split() if w]
    chunks, start = [], 0
    while start < len(words):
        text = " ".join(words[start : start + size])
        chunks.append(Chunk(f"{doc_id}~{len(chunks)}", doc_id, "", text, "fixed", meta))
        start += size - overlap
    return chunks


def load_chunks(source: Path, strategy: str = "heading") -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(source.glob("*.md")):
        meta, body = parse_doc(path)
        doc_id = meta.get("source", path.stem)
        fn = chunk_by_heading if strategy == "heading" else chunk_fixed
        chunks.extend(fn(doc_id, meta, body))
    return chunks


def build_index(source: Path, strategy: str = "heading") -> dict:
    chunks = load_chunks(source, strategy)
    return {
        "strategy": strategy,
        "chunks": [asdict(c) for c in chunks],
        "embeddings": {c.id: embed(f"{c.heading}. {c.text}") for c in chunks},
    }


def load_index(path: Path = INDEX_PATH, source: Path = ROOT / "data" / "docs") -> dict:
    if path.exists():
        return read_json(path)
    return build_index(source)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(ROOT / "data" / "docs"))
    ap.add_argument("--strategy", choices=["heading", "fixed"], default="heading")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    if INDEX_PATH.exists() and not args.rebuild:
        print(f"Index exists at {INDEX_PATH}; pass --rebuild to recreate")
        return
    index = build_index(Path(args.source), args.strategy)
    write_json(INDEX_PATH, index)
    docs = {c["doc"] for c in index["chunks"]}
    print(f"Indexed {len(index['chunks'])} chunks from {len(docs)} docs ({args.strategy}) -> {INDEX_PATH}")


if __name__ == "__main__":
    main()
