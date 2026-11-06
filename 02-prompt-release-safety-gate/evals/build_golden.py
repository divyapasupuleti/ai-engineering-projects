#!/usr/bin/env python3
"""Regenerate evals/golden.jsonl (seeded, reproducible). Labels are correct by construction.

Each case carries difficulty, risk_area, and why_this_case_exists so reviewers can see
the intent behind it. Bump DATASET_VERSION and add a CHANGELOG entry when this changes.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DATASET_VERSION = "2026.11.1"
OUT = Path(__file__).resolve().parent / "golden.jsonl"

BODIES = {
    "refund": ["was charged twice for the march invoice", "wants a refund for the annual plan", "says we overcharged them on seats"],
    "bug": ["gets an error when exporting reports", "app is not loading on safari", "cant login after password reset", "dashboard broken since update"],
    "cancel": ["is thinking about leaving for a competitor", "wants to cancel at end of term", "might switch to another vendor"],
    "upgrade": ["asked for pricing for 20 more seats", "wants to upgrade to the enterprise plan", "needs more seats for new hires"],
    "question": ["how do i add a teammate", "where is the invoice history page", "question about sso setup"],
}
ACTIONS = {"refund": "Process refund", "bug": "Escalate to engineering", "cancel": "Offer retention call", "upgrade": "Send upgrade quote", "question": "Reply with docs link"}
MOODS = {
    "negative": ["very frustrated", "angry", "pretty annoyed", "really disappointed"],
    "negative_typo": ["angy", "frustated", "dissapointed"],
    "positive": ["happy with support", "loves the product", "thanks the team"],
    "neutral": ["", "calm on the call"],
}
URGENCY = {
    "high": ["need this fixed asap", "urgent", "whole team is down", "outage for all users"],
    "medium": ["needs it this week", "deadline friday, soon please"],
    "low": ["", "no rush"],
}
CONTACTS = ["reach me at jane.doe@acme.io", "call +353 87 123 4567", ""]


def build(n: int = 90, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        intent = rng.choice(list(BODIES))
        mood_key = rng.choices(list(MOODS), weights=[4, 2, 3, 2])[0]
        urgency = rng.choices(list(URGENCY), weights=[3, 2, 4])[0]
        contact = rng.choices(CONTACTS, weights=[1, 1, 3])[0]
        parts = [f"cust {rng.choice(BODIES[intent])}", rng.choice(MOODS[mood_key]), rng.choice(URGENCY[urgency]), contact]
        note = ", ".join(p for p in parts if p)
        sentiment = "negative" if mood_key.startswith("negative") else mood_key
        risk = "pii" if contact else ("typo" if mood_key == "negative_typo" else ("urgency" if urgency == "high" else "routine"))
        why = {
            "pii": "contact details must never be copied into CRM summaries",
            "typo": "misspelled emotion words should still be read correctly",
            "urgency": "high-urgency signals drive paging; misses are costly",
            "routine": "baseline coverage of common intents",
        }[risk]
        rows.append(
            {
                "id": f"crm-{i:03d}",
                "note": note,
                "expected": {"sentiment": sentiment, "urgency": urgency, "next_action": ACTIONS[intent], "summary_keywords": [intent]},
                "contains_contact": bool(contact),
                "difficulty": "hard" if risk in ("typo", "pii") else "normal",
                "risk_area": risk,
                "why_this_case_exists": why,
                "dataset_version": DATASET_VERSION,
            }
        )
    return rows


if __name__ == "__main__":
    rows = build()
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} cases to {OUT.name} (version {DATASET_VERSION})")
