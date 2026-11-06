import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from generate_docs import generate  # noqa: E402
from intake import classify, normalise, process  # noqa: E402

DOCS = generate(80)


def first(scenario, doc_type=None):
    return next(d for d in DOCS if d["scenario"] == scenario and (doc_type is None or d["truth"]["doc_type"] == doc_type))


class IntakeTests(unittest.TestCase):
    def test_ocr_digit_confusions_are_corrected(self):
        fixes = []
        self.assertEqual(normalise("1,2O5.S0", "money", fixes, "total"), 1205.5)
        self.assertTrue(fixes)

    def test_classifier(self):
        self.assertEqual(classify(["TAX INVOICE", "VAT No: IE1", "Due Date: x"])[0], "invoice")
        self.assertEqual(classify(["hello world"])[0], "unknown")

    def test_clean_invoice_auto_approved_and_correct(self):
        d = first("clean", "invoice")
        ex = process(d, set())
        self.assertEqual(ex.route, "auto_approve")
        self.assertEqual(ex.fields, d["truth"]["fields"])

    def test_bad_scan_uses_vision_fallback(self):
        ex = process(first("bad_scan"), set())
        self.assertTrue(ex.used_vision)
        self.assertGreater(ex.cost, 0.01)

    def test_handwritten_total_goes_to_review(self):
        self.assertEqual(process(first("handwritten_total"), set()).route, "human_review")

    def test_duplicate_invoice_number_flagged(self):
        d = first("clean", "invoice")
        seen = set()
        process(d, seen)
        again = process(d, seen)
        self.assertTrue(any("duplicate" in r for r in again.rule_failures))


if __name__ == "__main__":
    unittest.main()
