#!/usr/bin/env python3
"""Generate seeded 'scanned' documents as OCR token streams with per-token confidence and ground truth.

    python generate_docs.py --n 80
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "documents.jsonl"

SUPPLIERS = [("ACME SUPPLIES LTD", "IE6388047V"), ("KERRY OFFICE GOODS", "IE9876543W"),
             ("LIFFEY LOGISTICS", "IE3344556AB"), ("CORK CLOUD SERVICES", "IE1122334K")]
BUYERS = ["Globex Corporation", "Initech", "Umbrella Health"]
SHOPS = ["CAFE CENTRAL", "DUBLIN TAXI CO", "HOTEL ST GEORGE"]
KNOWN_POS = ["PO-7781", "PO-7790", "PO-7802", "PO-7815", "PO-7833"]
CONFUSE = {"0": "O", "1": "l", "5": "S", "8": "B", "2": "Z"}
VAT_RATE = 0.23


def money(x: float) -> str:
    return f"{x:,.2f}"


def make_truth(rng: random.Random, i: int) -> dict:
    kind = rng.choices(["invoice", "receipt", "purchase_order"], [0.6, 0.25, 0.15])[0]
    d = date(2026, 8, 1) + timedelta(days=rng.randint(0, 90))
    if kind == "invoice":
        sup, vat_id = rng.choice(SUPPLIERS)
        subtotal = round(rng.randint(20, 900) * 5.0, 2)
        vat = round(subtotal * VAT_RATE, 2)
        return {"doc_type": "invoice", "fields": {
            "supplier": sup, "invoice_number": f"INV-2026-{1000 + i:04d}", "invoice_date": d.isoformat(),
            "due_date": (d + timedelta(days=30)).isoformat(), "vat_id": vat_id, "po_number": rng.choice(KNOWN_POS),
            "buyer": rng.choice(BUYERS), "subtotal": subtotal, "vat": vat, "total": round(subtotal + vat, 2)}}
    if kind == "receipt":
        total = round(rng.randint(400, 25000) / 100, 2)
        return {"doc_type": "receipt", "fields": {"merchant": rng.choice(SHOPS), "date": d.isoformat(),
                                                   "card_last4": f"{rng.randint(1000, 9999)}", "total": total}}
    total = round(rng.randint(50, 2000) * 10.0, 2)
    return {"doc_type": "purchase_order", "fields": {"po_number": f"PO-{7900 + i}", "order_date": d.isoformat(),
                                                      "supplier": rng.choice(SUPPLIERS)[0], "total": total}}


def render_lines(t: dict) -> list[str]:
    f = t["fields"]
    if t["doc_type"] == "invoice":
        return [f["supplier"], "TAX INVOICE", f"Invoice No: {f['invoice_number']}", f"Invoice Date: {f['invoice_date']}",
                f"Due Date: {f['due_date']}", f"VAT No: {f['vat_id']}", f"PO Number: {f['po_number']}",
                f"Bill To: {f['buyer']}", "Description Qty Unit Amount", f"Professional services 1 {money(f['subtotal'])} {money(f['subtotal'])}",
                f"Subtotal: {money(f['subtotal'])}", f"VAT 23%: {money(f['vat'])}", f"Total Due: EUR {money(f['total'])}"]
    if t["doc_type"] == "receipt":
        return [f["merchant"], "RECEIPT", f"Date: {f['date']}", f"Card **** {f['card_last4']}",
                "Thank you for your visit", f"Total: EUR {money(f['total'])}"]
    return ["PURCHASE ORDER", f"PO Number: {f['po_number']}", f"Order Date: {f['order_date']}",
            f"Supplier: {f['supplier']}", "Ship To: 1 Grand Canal Dock, Dublin 2", f"Total: EUR {money(f['total'])}"]


def corrupt(token: str, rng: random.Random, p: float) -> str:
    return "".join(CONFUSE[c] if c in CONFUSE and rng.random() < p else c for c in token)


def generate(n: int, seed: int = 17) -> list[dict]:
    rng = random.Random(seed)
    docs = []
    seen_numbers: list[str] = []
    for i in range(n):
        truth = make_truth(rng, i)
        scenario = rng.choices(["clean", "ocr_noise", "handwritten_total", "bad_scan", "business_error"],
                               [0.58, 0.15, 0.1, 0.09, 0.08])[0]
        if scenario == "business_error" and truth["doc_type"] == "invoice":
            if seen_numbers and rng.random() < 0.5:
                truth["fields"]["invoice_number"] = rng.choice(seen_numbers)
                truth["issue"] = "duplicate_invoice_number"
            else:
                truth["fields"]["total"] = round(truth["fields"]["total"] + rng.choice([10, 50, 100]), 2)
                truth["issue"] = "totals_do_not_add_up"
        elif scenario == "business_error":
            scenario = "clean"
        if truth["doc_type"] == "invoice" and "issue" not in truth:
            seen_numbers.append(truth["fields"]["invoice_number"])
        lines = render_lines(truth)
        noisy_line = rng.randrange(2, len(lines))
        pages = []
        for li, line in enumerate(lines):
            toks = []
            for tok in line.split(" "):
                conf = rng.uniform(0.93, 0.995)
                text = tok
                if scenario == "bad_scan":
                    conf = rng.uniform(0.35, 0.7)
                    text = corrupt(tok, rng, 0.35)
                elif scenario == "ocr_noise" and li == noisy_line and any(c.isdigit() for c in tok):
                    conf = rng.uniform(0.55, 0.8)
                    text = corrupt(tok, rng, 0.6)
                elif scenario == "handwritten_total" and li == len(lines) - 1 and any(c.isdigit() for c in tok):
                    conf = rng.uniform(0.4, 0.65)
                    digits = [c for c in tok]
                    pos = [k for k, c in enumerate(digits) if c.isdigit()]
                    k = rng.choice(pos)
                    digits[k] = str((int(digits[k]) + rng.randint(1, 8)) % 10)
                    text = "".join(digits)
                toks.append({"text": text, "conf": round(conf, 3)})
            pages.append(toks)
        docs.append({"doc_id": f"doc-{i:03d}", "scenario": scenario, "ocr_lines": pages,
                     "clean_lines": lines, "truth": truth})
    return docs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=80)
    args = ap.parse_args()
    docs = generate(args.n)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(json.dumps(d) for d in docs) + "\n")
    print(f"wrote {len(docs)} documents to {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
