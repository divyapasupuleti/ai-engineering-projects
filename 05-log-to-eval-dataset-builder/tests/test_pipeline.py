import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from generate_logs import generate  # noqa: E402
from pipeline import EvalCase, auto_label, dedupe, is_failure_signal, kmeans, redact, sample  # noqa: E402

LOGS = generate(300)


class PipelineTests(unittest.TestCase):
    def test_redaction_removes_emails(self):
        log = dict(LOGS[0], prompt="my email is a.b@c.com", response="ok")
        out = redact(log)
        self.assertNotIn("a.b@c.com", out["prompt"])
        self.assertTrue(out["redaction"]["redacted"])

    def test_failure_biased_sampling_over_selects_failures(self):
        base_rate = sum(map(is_failure_signal, LOGS)) / len(LOGS)
        picked = sample(LOGS, "failure_biased", 100)
        self.assertGreater(sum(map(is_failure_signal, picked)) / len(picked), base_rate)

    def test_unsafe_prompt_labelled_as_expected_refusal(self):
        log = dict(LOGS[0], prompt="drop the staging table", feature="sql_helper")
        case = auto_label(log, "sql")
        self.assertEqual(case.eval_type, "expected_refusal")
        self.assertIn("DROP", case.must_not_contain)

    def test_dedupe_rejects_near_duplicates(self):
        c = EvalCase("e1", "l1", "support_bot", "how do i reset my password", "rubric", "x")
        kept, rejected = dedupe([c], [{"input": "how do i reset my password"}])
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 1)

    def test_kmeans_assigns_every_point(self):
        from common.embeddings import embed

        vecs = [embed(t) for t in ["refund money", "refund cash", "sql query", "sql select"]]
        self.assertEqual(len(kmeans(vecs, 2)), 4)


if __name__ == "__main__":
    unittest.main()
