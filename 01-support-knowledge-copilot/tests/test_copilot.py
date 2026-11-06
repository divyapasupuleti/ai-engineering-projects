import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from answer import answer_question, verify_citations  # noqa: E402
from ingest import build_index, chunk_by_heading  # noqa: E402
from retrieval import Retriever, rrf  # noqa: E402

INDEX = build_index(PROJECT / "data" / "docs")


class CopilotTests(unittest.TestCase):
    def test_heading_chunking_keeps_sections(self):
        chunks = chunk_by_heading("d", {}, "# T\n## A\nalpha text\n## B\nbeta text")
        self.assertEqual([c.heading for c in chunks], ["A", "B"])

    def test_rrf_rewards_items_in_both_lists(self):
        fused = rrf([[("a", 1), ("b", 1)], [("b", 1), ("c", 1)]], [1, 1])
        self.assertEqual(fused[0][0], "b")

    def test_error_code_retrieved_by_hybrid(self):
        hits = Retriever(INDEX, "hybrid").search("What does ERR-4012 mean?")
        self.assertEqual(hits[0].chunk["doc"], "troubleshooting-guide")

    def test_answer_has_verified_citations(self):
        ans = answer_question("How long do customers have to request a refund?", Retriever(INDEX))
        self.assertFalse(ans.refused)
        self.assertTrue(ans.citations)
        self.assertTrue(all(v.supported for v in ans.verdicts))

    def test_unanswerable_question_is_refused(self):
        ans = answer_question("What is the parental leave policy?", Retriever(INDEX))
        self.assertTrue(ans.refused)
        self.assertTrue(ans.closest_sections)

    def test_bad_citation_is_caught(self):
        ans = answer_question("How long do customers have to request a refund?", Retriever(INDEX), inject_bad_citation=True)
        self.assertTrue(ans.could_not_verify)

    def test_verify_flags_unsupported_claim(self):
        chunks = {"x#0": {"text": "Refunds are issued within 5 business days."}}
        verdicts = verify_citations("The moon is made of cheese. [x#0]", chunks)
        self.assertFalse(verdicts[0].supported)


if __name__ == "__main__":
    unittest.main()
