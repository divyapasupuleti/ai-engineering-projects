import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from cache import SemanticCache, classify, signature  # noqa: E402
from gateway import CacheGateway  # noqa: E402


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.gw = CacheGateway(SemanticCache(threshold=0.8))

    def test_paraphrase_served_from_semantic_cache(self):
        self.gw.handle("acme", "ana", "How do I reset my password?", "reset_password", 0)
        r = self.gw.handle("globex", "dev", "how can i reset my password thanks", "reset_password", 10)
        self.assertIn(r.source, ("semantic", "exact"))
        self.assertEqual(r.cost, 0.0)

    def test_entity_mismatch_rejected(self):
        self.assertNotEqual(signature("price of the pro plan"), signature("price of the starter plan"))
        self.gw.handle("acme", "ana", "How much does the pro plan cost?", "price:pro", 0)
        r = self.gw.handle("acme", "ana", "How much does the starter plan cost?", "price:starter", 1)
        self.assertEqual(r.answer_id, "price:starter")

    def test_tenant_isolation(self):
        self.gw.handle("acme", "ana", "How many seats does our account have?", "seats:acme", 0)
        r = self.gw.handle("globex", "dev", "How many seats does our account have?", "seats:globex", 1)
        self.assertEqual(r.answer_id, "seats:globex")

    def test_realtime_and_ids_bypass(self):
        self.assertFalse(classify("where is orde r7310??").cacheable)
        self.assertFalse(classify("What is the status of order 4411?").cacheable)

    def test_tag_invalidation_and_ttl(self):
        c = self.gw.cache
        self.gw.handle("acme", "ana", "How much does the pro plan cost?", "price:pro:v1", 0)
        self.assertEqual(c.invalidate_tag("pricing"), 1)
        r = self.gw.handle("acme", "ana", "How much does the pro plan cost?", "price:pro:v2", 1)
        self.assertEqual(r.source, "upstream")
        self.gw.handle("acme", "ana", "How do I export my data?", "export", 0)
        r = self.gw.handle("acme", "ana", "How do I export my data?", "export", 8 * 24 * 3600)
        self.assertEqual(r.source, "upstream")


if __name__ == "__main__":
    unittest.main()
