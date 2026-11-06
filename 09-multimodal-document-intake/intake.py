"""Document intake pipeline: OCR quality gate -> vision fallback -> classify -> extract -> rules -> route."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

OCR_COST, VISION_COST = 0.0015, 0.012
OCR_FALLBACK_BELOW = 0.75
AUTO_APPROVE_FIELD_CONF = 0.85
KNOWN_POS = {"PO-7781", "PO-7790", "PO-7802", "PO-7815", "PO-7833"}
TODAY = date(2026, 11, 6)
VAT_RATE = 0.23

TYPE_KEYWORDS = {
    "invoice": ["invoice", "vat", "due", "bill", "subtotal"],
    "receipt": ["receipt", "card", "thank", "visit"],
    "purchase_order": ["purchase", "order", "ship", "po"],
}

SCHEMAS: dict[str, dict[str, tuple[str, str]]] = {
    "invoice": {
        "supplier": (r"^(.+)$", "line0"),
        "invoice_number": (r"Invoice No:\s*(\S+)", "id"),
        "invoice_date": (r"Invoice Date:\s*(\S+)", "date"),
        "due_date": (r"Due Date:\s*(\S+)", "date"),
        "vat_id": (r"VAT No:\s*(\S+)", "vat_id"),
        "po_number": (r"PO Number:\s*(\S+)", "id"),
        "buyer": (r"Bill To:\s*(.+)$", "text"),
        "subtotal": (r"Subtotal:\s*(\S+)", "money"),
        "vat": (r"VAT 23%:\s*(\S+)", "money"),
        "total": (r"Total Due:\s*EUR\s*(\S+)", "money"),
    },
    "receipt": {
        "merchant": (r"^(.+)$", "line0"),
        "date": (r"Date:\s*(\S+)", "date"),
        "card_last4": (r"Card \*{4}\s*(\S+)", "digits"),
        "total": (r"Total:\s*EUR\s*(\S+)", "money"),
    },
    "purchase_order": {
        "po_number": (r"PO Number:\s*(\S+)", "id"),
        "order_date": (r"Order Date:\s*(\S+)", "date"),
        "supplier": (r"Supplier:\s*(.+)$", "text"),
        "total": (r"Total:\s*EUR\s*(\S+)", "money"),
    },
}
DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8", "Z": "2"})


@dataclass
class Extraction:
    doc_id: str
    doc_type: str
    fields: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    corrections: list[str] = field(default_factory=list)
    rule_failures: list[str] = field(default_factory=list)
    used_vision: bool = False
    ocr_mean_conf: float = 0.0
    cost: float = 0.0
    route: str = ""
    route_reasons: list[str] = field(default_factory=list)


def vision_model(doc: dict) -> list[list[dict]]:
    """Stand-in for a multimodal model reading the page image: higher accuracy, 8x the cost."""
    return [[{"text": t, "conf": 0.9} for t in line.split(" ")] for line in doc["clean_lines"]]


def classify(lines: list[str]) -> tuple[str, float]:
    text = " ".join(lines).lower()
    scores = {k: sum(w in text for w in kws) for k, kws in TYPE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    return (best if scores[best] >= 2 else "unknown"), round(scores[best] / total, 2)


def normalise(value: str, kind: str, corrections: list[str], name: str) -> Any:
    if kind in ("money", "digits", "date"):
        fixed = value.translate(DIGIT_FIX)
        if fixed != value:
            corrections.append(f"{name}: '{value}' -> '{fixed}'")
        value = fixed
    if kind == "money":
        return round(float(value.replace(",", "")), 2)
    if kind == "date":
        return date.fromisoformat(value).isoformat()
    if kind in ("id", "vat_id"):
        if kind == "id":
            prefix, _, rest = value.partition("-")
            fixed = f"{prefix}-{rest.translate(DIGIT_FIX)}"
        else:
            fixed = value[:2] + value[2:9].translate(DIGIT_FIX) + value[9:]
        if fixed != value:
            corrections.append(f"{name}: '{value}' -> '{fixed}'")
        return fixed
    return value


def extract(doc_id: str, doc_type: str, ocr_lines: list[list[dict]]) -> Extraction:
    ex = Extraction(doc_id, doc_type)
    lines = [" ".join(t["text"] for t in line) for line in ocr_lines]
    for name, (pattern, kind) in SCHEMAS.get(doc_type, {}).items():
        search_lines = lines[:1] if kind == "line0" else lines
        for li, line in enumerate(search_lines):
            m = re.search(pattern, line)
            if not m:
                continue
            raw = m.group(1).strip()
            toks = [t for t in ocr_lines[li] if t["text"] in raw.split(" ") or raw in t["text"]]
            conf = min((t["conf"] for t in toks), default=0.5)
            try:
                ex.fields[name] = normalise(raw, kind, ex.corrections, name)
                ex.confidence[name] = round(conf if not any(c.startswith(name) for c in ex.corrections) else conf * 0.9, 3)
            except ValueError:
                ex.fields[name] = None
                ex.confidence[name] = 0.0
            break
        else:
            ex.fields[name], ex.confidence[name] = None, 0.0
    return ex


def business_rules(ex: Extraction, seen_invoice_numbers: set[str]) -> list[str]:
    f, fails = ex.fields, []
    missing = [k for k, v in f.items() if v is None]
    if missing:
        fails.append(f"missing/unreadable: {', '.join(missing)}")
    if ex.doc_type == "invoice" and not missing:
        if abs(f["subtotal"] + f["vat"] - f["total"]) > 0.01:
            fails.append(f"subtotal + VAT ({f['subtotal'] + f['vat']:.2f}) != total ({f['total']:.2f})")
        if abs(f["subtotal"] * VAT_RATE - f["vat"]) > 0.02:
            fails.append("VAT is not 23% of subtotal")
        if f["due_date"] < f["invoice_date"]:
            fails.append("due date before invoice date")
        if not re.fullmatch(r"IE\d{7}[A-Z]{1,2}", f["vat_id"]):
            fails.append(f"VAT id {f['vat_id']} has invalid format")
        if f["po_number"] not in KNOWN_POS:
            fails.append(f"PO {f['po_number']} not found in ERP")
        if f["invoice_number"] in seen_invoice_numbers:
            fails.append(f"duplicate invoice number {f['invoice_number']}")
    for k in ("invoice_date", "date", "order_date"):
        if f.get(k) and f[k] > TODAY.isoformat():
            fails.append(f"{k} is in the future")
    return fails


def process(doc: dict, seen_invoice_numbers: set[str]) -> Extraction:
    ocr = doc["ocr_lines"]
    mean_conf = sum(t["conf"] for line in ocr for t in line) / sum(len(line) for line in ocr)
    cost = OCR_COST
    used_vision = False
    if mean_conf < OCR_FALLBACK_BELOW:
        ocr = vision_model(doc)
        cost += VISION_COST
        used_vision = True
    doc_type, _ = classify([" ".join(t["text"] for t in line) for line in ocr])
    ex = extract(doc["doc_id"], doc_type, ocr)
    ex.used_vision, ex.ocr_mean_conf, ex.cost = used_vision, round(mean_conf, 3), cost
    if doc_type == "unknown":
        ex.route, ex.route_reasons = "reject", ["could not classify document"]
        return ex
    ex.rule_failures = business_rules(ex, seen_invoice_numbers)
    low = [k for k, c in ex.confidence.items() if c < AUTO_APPROVE_FIELD_CONF]
    if ex.rule_failures:
        ex.route, ex.route_reasons = "human_review", ex.rule_failures
    elif low:
        ex.route, ex.route_reasons = "human_review", [f"low confidence: {', '.join(low)}"]
    else:
        ex.route = "auto_approve"
    if doc_type == "invoice" and ex.fields.get("invoice_number"):
        seen_invoice_numbers.add(ex.fields["invoice_number"])
    return ex
