import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from common.io import read_json, read_jsonl  # noqa: E402
from gate import decide, score_case, should_run, summarise  # noqa: E402
from schema import parse_output  # noqa: E402

CFG = read_json(PROJECT / "gate_config.json")
GOLDEN = read_jsonl(PROJECT / "evals" / "golden.jsonl")
PROD = read_json(PROJECT / "prompts" / "crm_summary.prod.json")


def run(prompt_file: str) -> dict:
    return summarise([score_case(read_json(PROJECT / "prompts" / prompt_file), c) for c in GOLDEN])


class GateTests(unittest.TestCase):
    def test_schema_rejects_prose_wrapped_json(self):
        parsed, errors = parse_output('Sure! {"summary": "x"}')
        self.assertIsNone(parsed)
        self.assertIn("output is not pure JSON", errors)

    def test_regressing_candidate_is_blocked(self):
        decision, reasons = decide(run("crm_summary.prod.json"), run("crm_summary.candidate.json"), CFG)
        self.assertEqual(decision, "BLOCK")
        self.assertTrue(any("safety" in r for r in reasons))

    def test_good_candidate_is_mergeable_and_better(self):
        base, cand = run("crm_summary.prod.json"), run("crm_summary.candidate_good.json")
        decision, _ = decide(base, cand, CFG)
        self.assertIn(decision, {"PASS", "WARN"})
        self.assertGreater(cand["pass_rate"], base["pass_rate"])

    def test_gate_skips_unrelated_changes(self):
        self.assertFalse(should_run(["README.md"], CFG["watch_paths"]))
        self.assertTrue(should_run(["prompts/crm_summary.prod.json"], CFG["watch_paths"]))

    def test_production_prompt_never_leaks_contacts(self):
        self.assertEqual(run("crm_summary.prod.json")["safety_failures"], 0)


if __name__ == "__main__":
    unittest.main()
