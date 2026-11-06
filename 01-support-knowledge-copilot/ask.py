#!/usr/bin/env python3
"""Ask the copilot a question.

    python ask.py "How long do I have to request a refund?"
    python ask.py "What does ERR-4012 mean?" --strategy sparse
    python ask.py "How long do I have to request a refund?" --inject-bad-citation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from answer import answer_question  # noqa: E402
from ingest import load_index  # noqa: E402
from retrieval import Retriever  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question")
    ap.add_argument("--strategy", choices=["hybrid", "dense", "sparse"], default="hybrid")
    ap.add_argument("--inject-bad-citation", action="store_true", help="demo: verification should catch it")
    args = ap.parse_args()
    retriever = Retriever(load_index(), args.strategy)
    print(json.dumps(answer_question(args.question, retriever, args.inject_bad_citation).to_dict(), indent=2))


if __name__ == "__main__":
    main()
