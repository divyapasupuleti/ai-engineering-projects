import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from approaches import FineTuned, KnowledgeFineTuned, KnowledgeRAG, PromptOnly  # noqa: E402
from lab import macro_f1  # noqa: E402
from make_data import fact_questions, kb, kb_docs, tickets  # noqa: E402


class LabTests(unittest.TestCase):
    def test_holdout_templates_only_in_test(self):
        train_texts = {t for t, _ in tickets(400, seed=1)}
        self.assertFalse(any("Ledger total does not match" in t for t in train_texts))

    def test_fine_tune_learns_jargon_prompt_only_cannot(self):
        ft = FineTuned(tickets(400, seed=1))
        self.assertEqual(ft.predict("Nimbus stuck at 99%"), "platform_sync")
        self.assertNotEqual(PromptOnly().predict("Nimbus stuck at 99%"), "platform_sync")

    def test_rag_follows_fact_update_fine_tune_does_not(self):
        q = "How many days do customers have to request a refund?"
        self.assertEqual(KnowledgeRAG(kb_docs(2)).answer(q), "14 days")
        self.assertEqual(KnowledgeFineTuned(fact_questions(seed=3), kb(1)).answer(q), "30 days")

    def test_macro_f1(self):
        self.assertEqual(macro_f1(["a", "b"], ["a", "b"]), 1.0)
        self.assertLess(macro_f1(["a", "b"], ["a", "a"]), 1.0)


if __name__ == "__main__":
    unittest.main()
