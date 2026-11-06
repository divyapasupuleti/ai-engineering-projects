#!/usr/bin/env python3
"""Seeded eval items: questions with key facts, outputs from two system versions, and two human annotators.

Each output has a hidden true quality (1-5). Text is composed so that quality shows up in observable
features (facts covered, citation, hallucinated claims, filler), which is what a judge can see.

    python generate_data.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOPICS = {
    "refund": [("Refunds are available within 14 days", "14 days"), ("refunds go back to the original card", "original card"),
               ("annual plans are refunded pro rata", "pro rata")],
    "sso": [("SAML SSO is on the Enterprise plan", "enterprise"), ("configure it under Settings > Security", "settings > security"),
            ("Okta and Azure AD are supported", "okta")],
    "export": [("exports run as background jobs", "background"), ("files over 2 GB are split", "2 gb"),
               ("Parquet and JSON formats are available", "parquet")],
    "api": [("the API allows 1000 requests per minute", "1000 requests"), ("429 responses include Retry-After", "retry-after"),
            ("use the next_cursor field to paginate", "next_cursor")],
    "billing": [("invoices are issued on the 1st", "1st"), ("VAT is added for EU customers", "vat"),
                ("you can change the billing contact in Ledger", "ledger")],
}
HALLUCINATIONS = ["This is guaranteed to work in every case.", "Refunds are always instant.", "All plans include unlimited seats.",
                  "This was fixed permanently last year."]
FILLER = ("Thank you so much for reaching out, we really appreciate your patience and we are always happy to help "
          "with any questions you might have about our product and services. ")


def compose(facts, quality: int, rng: random.Random, topic: str) -> str:
    n_facts = {5: 3, 4: 2, 3: 2, 2: 1, 1: 0}[quality]
    parts = [f[0] + "." for f in rng.sample(facts, n_facts)]
    if quality <= 2 or (quality == 3 and rng.random() < 0.5):
        parts.append(rng.choice(HALLUCINATIONS))
    if quality == 1 and not parts:
        parts.append("I'm not sure, please check the website.")
    if quality <= 3 and rng.random() < 0.5:
        parts.insert(0, FILLER)
    if quality >= 4 or (quality == 3 and rng.random() < 0.4):
        parts.append(f"[kb:{topic}]")
    return " ".join(parts)


def generate(n: int = 150, seed: int = 14) -> list[dict]:
    rng = random.Random(seed)
    items = []
    for i in range(n):
        topic = rng.choice(list(TOPICS))
        facts = TOPICS[topic]
        q_v1 = rng.choices([1, 2, 3, 4, 5], [0.08, 0.14, 0.22, 0.32, 0.24])[0]
        shift = rng.choices([-1, 0, 1], [0.12, 0.5, 0.38])[0]
        if topic == "refund":
            shift = rng.choices([-2, -1, 0], [0.35, 0.4, 0.25])[0]
        q_v2 = max(1, min(5, q_v1 + shift))

        def human(q):
            return max(1, min(5, q + rng.choices([-1, 0, 1], [0.13, 0.74, 0.13])[0]))

        items.append({
            "id": f"item-{i:03d}", "category": topic, "input": f"Customer question about {topic}",
            "reference": " ".join(f[0] + "." for f in facts), "key_facts": [f[1] for f in facts],
            "outputs": {"v1": compose(facts, q_v1, rng, topic), "v2": compose(facts, q_v2, rng, topic)},
            "true_quality": {"v1": q_v1, "v2": q_v2},
            "human": {"annotator_a": human(q_v1), "annotator_b": human(q_v1)} if i < 120 else None,
        })
    return items


def main() -> None:
    items = generate()
    out = ROOT / "data" / "items.jsonl"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(json.dumps(x) for x in items) + "\n")
    print(f"wrote {len(items)} items ({sum(1 for x in items if x['human'])} with two human labels) to data/items.jsonl")


if __name__ == "__main__":
    main()
