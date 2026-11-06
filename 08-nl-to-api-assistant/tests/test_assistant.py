import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from assistant import Assistant, load_operations, validate, validate_call  # noqa: E402


class AssistantTests(unittest.TestCase):
    def test_validator_enforces_enum_and_bounds(self):
        schema = {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number", "minimum": 0.01}}}
        self.assertTrue(validate({"amount": 0}, schema))
        self.assertTrue(validate({}, schema))
        self.assertEqual(validate({"amount": 5}, schema), [])
        op = load_operations()["updateCustomer"]
        self.assertTrue(validate_call(op, {"customer_id": "c_1", "body": {"plan": "gold"}}))

    def test_chained_refund_resolves_ids(self):
        bot = Assistant()
        res = bot.handle("Refund 200 EUR for Umbrella Health because of a duplicate charge")
        self.assertEqual(res.status, "done")
        self.assertEqual(bot.api.refunds[0]["invoice_id"], "inv_9004")

    def test_write_needs_confirmation(self):
        bot = Assistant()
        res = bot.handle("Upgrade Initech to the enterprise plan", confirm=lambda req: False)
        self.assertEqual(res.status, "cancelled")
        self.assertEqual(bot.api.db["customers"]["c_102"]["plan"], "starter")

    def test_delete_blocked_for_non_admin(self):
        bot = Assistant(role="support")
        self.assertEqual(bot.handle("Delete customer Initech").status, "blocked")
        self.assertIn("c_102", bot.api.db["customers"])

    def test_ambiguous_customer_asks(self):
        res = Assistant().handle("Show invoices for Acme")
        self.assertEqual(res.status, "needs_clarification")
        self.assertIn("Acme Labs", res.message)

    def test_dry_run_executes_nothing(self):
        bot = Assistant()
        res = bot.handle("Open an urgent priority ticket for Initech about login loop on mobile", dry_run=True)
        self.assertEqual(res.status, "dry_run")
        self.assertEqual(bot.api.log, [])


if __name__ == "__main__":
    unittest.main()
