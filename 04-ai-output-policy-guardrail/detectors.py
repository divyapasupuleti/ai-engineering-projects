"""Deterministic detectors (cheap, exact) and a judge (nuanced). Every finding carries an evidence span."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from common.text import overlap_ratio, split_sentences

PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "phone": re.compile(r"(?<!\w)\+?\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3}[\s-]?\d{3,4}(?!\w)"),
    "credit_card": re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
    "api_key": re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7,}\b"),
}
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|percent|days?|hours?|euros?|dollars?|x)?", re.I)
SOFTEN = {
    "is guaranteed to cure": "may help with",
    "guaranteed to cure": "may help with",
    "is 100% safe for everyone": "is generally well tolerated, but check with a doctor",
    "100% safe": "generally considered safe",
    "no risk at all": "a low but non-zero risk",
    "you will definitely win": "you may have a reasonable case",
    "guaranteed returns": "potential returns",
    "cannot fail": "is unlikely to fail",
}


@dataclass
class Finding:
    policy_id: str
    severity: str
    action: str
    evidence: str
    detail: str
    detector: str
    confidence: float = 1.0


def luhn_ok(digits: str) -> bool:
    nums = [int(d) for d in re.sub(r"\D", "", digits)][::-1]
    if not 13 <= len(nums) <= 19:
        return False
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(nums))
    return total % 10 == 0


def detect_schema(output: str, expects_json: bool, policy: dict) -> list[Finding]:
    if not expects_json:
        return []
    try:
        json.loads(output)
        return []
    except json.JSONDecodeError as exc:
        return [Finding(policy["id"], policy["severity"], policy["action"], output[:60], f"invalid JSON: {exc.msg}", "schema")]


def detect_pii(output: str, policy: dict, allowed: set[str]) -> list[Finding]:
    findings = []
    for kind in policy.get("types", []):
        if kind in allowed:
            continue
        for m in PII_PATTERNS[kind].finditer(output):
            if kind == "credit_card" and not luhn_ok(m.group(0)):
                continue
            if kind == "phone" and luhn_ok(m.group(0)):
                continue
            findings.append(Finding(policy["id"], policy["severity"], policy["action"], m.group(0), f"{kind} detected", "pii"))
    return findings


def detect_keywords(output: str, policy: dict) -> list[Finding]:
    low = output.lower()
    return [
        Finding(policy["id"], policy["severity"], policy["action"], p, f"matched pattern '{p}'", policy["detector"])
        for p in policy.get("patterns", [])
        if p in low
    ]


def judge_unsupported_claims(output: str, context: str, policy: dict, strict: bool = False) -> list[Finding]:
    """Stand-in for an LLM judge: numeric claims must appear in the context and the sentence must overlap it.

    Two passes (lenient + strict) are run for high-risk features; disagreement routes to a human.
    """
    if not context:
        return []
    findings = []
    ctx_numbers = {n.strip().lower() for n in NUMBER_RE.findall(context)}
    threshold = 0.5 if strict else 0.3
    for sent in split_sentences(output):
        numbers = {n.strip().lower() for n in NUMBER_RE.findall(sent)}
        unsupported = {n for n in numbers if n and n not in ctx_numbers}
        support = overlap_ratio(sent, context)
        if unsupported or (strict and numbers and support < threshold):
            detail = f"numbers not in context: {sorted(unsupported)}" if unsupported else f"weak support ({support:.2f})"
            findings.append(Finding(policy["id"], policy["severity"], policy["action"], sent, detail, "judge", 0.8 if strict else 0.7))
    return findings


def redact(output: str, findings: list[Finding]) -> str:
    for f in findings:
        if f.policy_id == "pii_leak":
            kind = f.detail.split()[0].upper()
            output = output.replace(f.evidence, f"[REDACTED_{kind}]")
    return output


def soften(output: str) -> str:
    for phrase, replacement in SOFTEN.items():
        output = re.sub(re.escape(phrase), replacement, output, flags=re.I)
    return output


def repair_json(output: str) -> str | None:
    start, end = output.find("{"), output.rfind("}")
    if start == -1 or end <= start:
        return None
    candidate = output[start : end + 1]
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return None
