"""The AI feature under test: messy customer note -> structured CRM summary.

`simulated_model` is a deterministic stand-in for an LLM that follows the prompt's rules,
so prompt changes produce reproducible behaviour changes in CI. Replace it with a provider
adapter (OpenAI / Anthropic) that sends `system_prompt` + `few_shot` + note.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.pricing import cost_usd, latency_ms  # noqa: E402
from common.text import count_tokens  # noqa: E402

INTENTS = {
    "refund": (("refund", "money back", "charged twice", "overcharged"), "Process refund"),
    "bug": (("error", "crash", "cant login", "can't login", "bug", "broken", "not loading"), "Escalate to engineering"),
    "cancel": (("cancel", "leaving", "switch to", "churn"), "Offer retention call"),
    "upgrade": (("more seats", "upgrade", "pricing for", "enterprise plan"), "Send upgrade quote"),
    "question": (("how do i", "how to", "where is", "question"), "Reply with docs link"),
}
CONTACT_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{7,}\d")


@dataclass
class ModelCall:
    raw_output: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    model: str


def _detect_intent(note: str) -> str:
    low = note.lower()
    for intent, (markers, _) in INTENTS.items():
        if any(m in low for m in markers):
            return intent
    return "question"


def _sentiment(note: str, rules: dict) -> str:
    words = set(re.findall(r"[a-z']+", note.lower()))
    if words & set(rules["negative_words"]):
        return "negative"
    if words & set(rules["positive_words"]):
        return "positive"
    return "neutral"


def _urgency(note: str, rules: dict) -> str:
    low = note.lower()
    if any(k in low for k in rules["high_urgency"]):
        return "high"
    if any(k in low for k in rules["medium_urgency"]):
        return "medium"
    return "low"


def simulated_model(prompt: dict, note: str) -> str:
    rules = prompt["rules"]
    intent = _detect_intent(note)
    core = re.sub(r"\s+", " ", note).strip().rstrip(".")
    contact = CONTACT_RE.search(core)
    if rules["redact_contacts"]:
        core = CONTACT_RE.sub("[contact]", core)
    summary = f"Customer {intent} request: {core}."
    if rules["style"] == "verbose":
        summary += " The account manager should review the full history, reach out personally, and confirm the customer feels heard"
        if contact:
            summary += f" via {contact.group(0)}"
        summary += "."
    words = summary.split()
    summary = " ".join(words[: rules["summary_max_words"]])
    payload = {
        "summary": summary,
        "sentiment": _sentiment(note, rules),
        "next_action": INTENTS[intent][1],
        "urgency": _urgency(note, rules),
        "confidence": 0.82 if intent != "question" else 0.6,
    }
    text = json.dumps(payload)
    wraps = int(hashlib.md5(note.encode()).hexdigest(), 16) % 4 == 0
    if not rules["json_only"] and wraps:
        text = "Sure! Here is the CRM summary you asked for:\n" + text
    return text


def run_prompt(prompt: dict, note: str) -> ModelCall:
    shots = " ".join(json.dumps(s) for s in prompt["few_shot"])
    in_tokens = count_tokens(prompt["system_prompt"] + shots + note)
    raw = simulated_model(prompt, note)
    out_tokens = count_tokens(raw)
    model = prompt["model"]
    return ModelCall(raw, in_tokens, out_tokens, latency_ms(model, out_tokens), cost_usd(model, in_tokens, out_tokens), model)
