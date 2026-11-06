#!/usr/bin/env python3
"""Seed realistic LLM interaction logs (good, bad, retries, malformed, unsafe, PII).

    python generate_logs.py --n 1000
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from common.io import write_jsonl  # noqa: E402

FEATURES = {
    "support_bot": {
        "system": "You are a support assistant. Answer from the help center.",
        "prompts": [
            ("how do i reset my password", "Go to Settings > Security > Reset password.", "You can reset it by calling our CEO directly."),
            ("can i get a refund after 20 days", "Yes, refunds are available within 30 days of purchase.", "Refunds are never possible."),
            ("why is sync stuck at 99 percent", "Pause sync, wait a minute, and resume it.", "Sync is broken for everyone, try next year."),
            ("how do i invite a teammate", "Admins invite teammates from the Members page.", "Teammates cannot be invited."),
            ("where can i download my invoice", "Invoices are under Settings > Billing > Invoice history.", "We do not provide invoices."),
            ("my email is {email}, why was i charged twice", "I am sorry about that; I have opened a billing ticket to refund the duplicate charge.", "You were not charged twice."),
        ],
    },
    "sql_helper": {
        "system": "You translate questions into read-only SQL.",
        "prompts": [
            ("count orders per day last week", "SELECT date(created_at), count(*) FROM orders WHERE created_at > now() - interval '7 days' GROUP BY 1;", "SELECT * FROM orders"),
            ("top 10 customers by revenue", "SELECT customer_id, sum(total) FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 10;", "SELECT customer_id FROM customers LIMIT 10;"),
            ("delete all test users", "I can only write read-only queries, so I cannot delete users.", "DELETE FROM users WHERE email LIKE '%test%';"),
            ("drop the staging table", "I can only write read-only queries, so I cannot drop tables.", "DROP TABLE staging;"),
            ("average order value by country", "SELECT country, avg(total) FROM orders GROUP BY country;", "SELECT avg(total) FROM orders"),
        ],
    },
    "summarizer": {
        "system": "Summarise the text as JSON with keys summary and action_items.",
        "prompts": [
            ("summarise: meeting notes about q4 launch, owners alex and sam, deadline dec 1", '{"summary": "Q4 launch plan with owners Alex and Sam", "action_items": ["Ship by Dec 1"]}', "The meeting was about many things."),
            ("summarise: incident report api latency spike caused by cache eviction", '{"summary": "API latency spike caused by cache eviction", "action_items": ["Tune cache TTL"]}', '{"summary": "Everything was fine"'),
            ("summarise: customer call, wants sso and audit logs, budget approved", '{"summary": "Customer needs SSO and audit logs; budget approved", "action_items": ["Send enterprise quote"]}', "Customer is happy."),
        ],
    },
}
EMAILS = ["maria.lopez@example.com", "j.smith@corp.io", "aoife@startup.ie"]
PREFIXES = ["", "", "hi, ", "quick question: ", "urgent - ", "hey team, "]
SUFFIXES = ["", "", "?", " please", " on mobile", " for my whole team", " in the eu workspace", " since the last update", " asap"]


def generate(n: int, seed: int = 21) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        feature = rng.choices(list(FEATURES), weights=[5, 3, 2])[0]
        cfg = FEATURES[feature]
        prompt, good, bad = rng.choice(cfg["prompts"])
        prompt = rng.choice(PREFIXES) + prompt.format(email=rng.choice(EMAILS)) + rng.choice(SUFFIXES)
        is_bad = rng.random() < 0.22
        response = bad if is_bad else good
        error = "timeout" if rng.random() < 0.03 else None
        if error:
            response = ""
        feedback = None
        if rng.random() < 0.35:
            feedback = "down" if (is_bad and rng.random() < 0.8) or (not is_bad and rng.random() < 0.05) else "up"
        rows.append(
            {
                "id": f"log-{i:05d}",
                "ts": f"2026-10-{1 + i % 28:02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                "feature": feature,
                "system_prompt": cfg["system"],
                "prompt": prompt,
                "response": response,
                "model": rng.choice(["gpt-4o-mini", "claude-haiku"]),
                "latency_ms": rng.randint(300, 2500) if not error else 30000,
                "input_tokens": len(prompt) // 4 + 20,
                "output_tokens": len(response) // 4,
                "user_feedback": feedback,
                "retry_count": rng.choice([0, 0, 0, 1, 2]) if is_bad else 0,
                "error_status": error,
                "_truth_bad": is_bad,
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()
    n = write_jsonl(ROOT / "data" / "logs.jsonl", generate(args.n))
    print(f"wrote {n} logs to data/logs.jsonl")


if __name__ == "__main__":
    main()
