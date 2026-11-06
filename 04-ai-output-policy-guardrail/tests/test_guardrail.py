import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from detectors import luhn_ok  # noqa: E402
from guardrail import CheckRequest, GuardrailService  # noqa: E402


def check(**kw):
    return GuardrailService().check(CheckRequest(feature="t", prompt="p", **kw))


class GuardrailTests(unittest.TestCase):
    def test_clean_output_is_approved(self):
        self.assertEqual(check(output="Use Settings, then Export.").action, "approve")

    def test_pii_is_redacted(self):
        d = check(output="Email priya@acme.com for help.")
        self.assertEqual(d.action, "rewrite")
        self.assertIn("[REDACTED_EMAIL]", d.final_output)

    def test_allowed_pii_passes(self):
        self.assertEqual(check(output="billing@acme.com", allowed_pii=["email"]).action, "approve")

    def test_unsafe_instruction_blocked(self):
        d = check(output="Just disable the smoke detector.")
        self.assertEqual(d.action, "block")
        self.assertIsNone(d.final_output)

    def test_overconfidence_softened(self):
        d = check(output="This is guaranteed to cure it.")
        self.assertIn("may help with", d.final_output)

    def test_json_repaired(self):
        d = check(output='Sure: {"a": 1}', expects_json=True)
        self.assertEqual(d.final_output, '{"a": 1}')

    def test_unrepairable_json_goes_to_review(self):
        self.assertEqual(check(output="not json", expects_json=True).action, "human_review")

    def test_unsupported_numeric_claim_needs_review(self):
        d = check(output="Refunds within 45 days.", context="Refunds within 30 days.")
        self.assertEqual(d.action, "human_review")

    def test_luhn(self):
        self.assertTrue(luhn_ok("4111 1111 1111 1111"))
        self.assertFalse(luhn_ok("1234 5678 9012 3456"))

    def test_every_decision_is_audited(self):
        svc = GuardrailService()
        svc.check(CheckRequest("t", "p", "hello"))
        self.assertEqual(svc.stats()["decisions"], 1)


if __name__ == "__main__":
    unittest.main()
