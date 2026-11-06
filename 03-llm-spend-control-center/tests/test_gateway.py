import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from classifier import classify  # noqa: E402
from gateway import BudgetExceeded, GatewayRequest, SpendGateway  # noqa: E402


class GatewayTests(unittest.TestCase):
    def test_classifier_tiers(self):
        self.assertEqual(classify("Extract the invoice number from this text").tier, 1)
        self.assertEqual(classify("Summarise this thread").tier, 2)
        self.assertEqual(classify("Analyze the churn risk and plan outreach").tier, 3)
        self.assertEqual(classify("Format this", risk_tags=["legal"]).tier, 3)

    def test_routes_simple_work_to_cheap_model(self):
        gw = SpendGateway()
        resp = gw.handle(GatewayRequest("support", "field_extract", "Extract the order id from: order 42"))
        self.assertEqual(resp.model, "gpt-4o-mini")

    def test_feature_override_forces_strong_model(self):
        gw = SpendGateway()
        resp = gw.handle(GatewayRequest("legal", "contract_review", "Format this clause"))
        self.assertEqual(resp.model, "claude-sonnet")

    def test_low_priority_blocked_when_budget_exhausted(self):
        gw = SpendGateway()
        gw.budgets["sales"]["daily_usd"] = 0.0001
        with self.assertRaises(BudgetExceeded):
            gw.handle(GatewayRequest("sales", "crm_cleanup", "Analyze this deal " * 50, priority="low"))

    def test_high_priority_served_with_override(self):
        gw = SpendGateway()
        gw.budgets["sales"]["daily_usd"] = 0.0001
        resp = gw.handle(GatewayRequest("sales", "deal_analysis", "Analyze this deal", priority="high"))
        self.assertTrue(resp.over_budget)

    def test_every_request_is_logged(self):
        gw = SpendGateway()
        gw.handle(GatewayRequest("engineering", "commit_summary", "Summarise these commits"))
        self.assertEqual(gw.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
