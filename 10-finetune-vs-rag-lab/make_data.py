"""Seeded datasets for the two lab tasks.

Task A (behaviour): route support tickets to 8 internal queues. Tickets use company jargon
  (Nimbus = sync engine, Gatekeeper = SSO, Ledger = billing portal) that a base model cannot know.
Task B (knowledge): answer product-fact questions. Four facts change between kb_v1 and kb_v2.
"""

from __future__ import annotations

import random

QUEUES = {
    "billing": ["Ledger shows a double charge for {month}", "refund for the {month} invoice please",
                "Ledger won't load my receipts", "why was my card charged twice", "need a VAT invoice for {month}",
                "Ledger total does not match the quote"],
    "identity": ["Gatekeeper rejects my Okta assertion", "cannot log in after password reset",
                 "Gatekeeper loop when signing in with Azure AD", "2FA code never arrives", "SSO login fails for new hires",
                 "Gatekeeper says certificate expired"],
    "platform_sync": ["Nimbus stuck at 99%", "Nimbus keeps duplicating folders", "files not syncing since {month}",
                      "Nimbus conflict copies everywhere", "desktop sync paused with error 0x80", "Nimbus uses 100% CPU"],
    "data_export": ["export to CSV times out", "need a full workspace export for audit", "Parquet export missing columns",
                    "export job stuck in queued", "download of export zip is corrupted", "schedule a weekly export"],
    "api": ["getting 429 rate limit errors", "webhook signature validation fails", "API returns 500 on /v2/items",
            "pagination cursor returns duplicates", "token scopes for the API", "Nimbus API endpoint deprecated?"],
    "mobile": ["iOS app crashes on launch", "Android app won't upload photos", "push notifications stopped on iPhone",
               "mobile app logs me out every day", "tablet layout broken", "offline mode on Android not saving"],
    "security": ["we think an account was compromised", "report a vulnerability in your login page",
                 "need your SOC 2 report", "suspicious logins from another country", "pen test findings to share",
                 "Gatekeeper audit log shows unknown admin"],
    "account_admin": ["add 10 seats to our plan", "transfer workspace ownership", "downgrade to Starter",
                      "remove a user who left the company", "change the billing contact", "merge two workspaces"],
}
MONTHS = ["January", "March", "June", "September", "October"]
PREFIX = ["", "hi, ", "urgent: ", "hello team - ", "quick one: "]
SUFFIX = ["", " thanks", " asap", " for our whole team", " since yesterday", " (enterprise customer)"]

FACTS_V1 = {
    "refund_window": ("How many days do customers have to request a refund?", "30 days"),
    "pro_price": ("What does the Pro plan cost per user?", "25 EUR"),
    "rate_limit": ("What is the API rate limit?", "600 requests per minute"),
    "sso_plan": ("Which plan includes SSO?", "Enterprise"),
    "retention": ("How long are deleted files kept?", "30 days"),
    "export_formats": ("Which export formats are supported?", "CSV and Parquet"),
    "support_hours": ("What are support hours?", "24/7 for Enterprise, 9-17 for others"),
    "seat_minimum": ("What is the minimum number of seats on Pro?", "3 seats"),
    "data_region": ("Where is EU customer data stored?", "Dublin and Frankfurt"),
    "mobile_os": ("Which iOS version is required?", "iOS 16 or later"),
}
CHANGED_IN_V2 = {"refund_window": "14 days", "pro_price": "29 EUR", "rate_limit": "1000 requests per minute",
                 "export_formats": "Parquet and JSON"}
PARAPHRASE = ["{q}", "quick question: {q}", "{q} I couldn't find it in the docs", "customer is asking: {q}",
              "can you tell me {q_lower}", "{q} (for a sales call)"]


def tickets(n: int, seed: int, noise: float = 0.05, include_holdout: bool = False) -> list[tuple[str, str]]:
    """The last template of every queue is held out of training so test accuracy measures generalisation."""
    rng = random.Random(seed)
    labels = list(QUEUES)
    out = []
    for _ in range(n):
        label = rng.choice(labels)
        pool = QUEUES[label] if include_holdout else QUEUES[label][:-1]
        text = rng.choice(PREFIX) + rng.choice(pool).format(month=rng.choice(MONTHS)) + rng.choice(SUFFIX)
        if rng.random() < noise:
            label = rng.choice(labels)
        out.append((text, label))
    return out


def kb(version: int) -> dict[str, str]:
    facts = {k: a for k, (_, a) in FACTS_V1.items()}
    if version == 2:
        facts.update(CHANGED_IN_V2)
    return facts


def kb_docs(version: int) -> list[tuple[str, str]]:
    facts = kb(version)
    return [(k, f"{FACTS_V1[k][0]} Answer: {facts[k]}.") for k in facts]


def fact_questions(seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    out = []
    for key, (q, _) in FACTS_V1.items():
        for tpl in rng.sample(PARAPHRASE, 3):
            out.append((tpl.format(q=q, q_lower=q[0].lower() + q[1:]), key))
    return out
