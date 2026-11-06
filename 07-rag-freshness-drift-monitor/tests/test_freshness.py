import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from drift import VectorIndex, run_probes  # noqa: E402
from freshness import build_manifest, classify_change, diff, stale_docs  # noqa: E402
from monitor import build_index, incremental_rebuild  # noqa: E402

V1 = build_manifest(PROJECT / "data" / "kb_v1")
V2 = build_manifest(PROJECT / "data" / "kb_v2")


class FreshnessTests(unittest.TestCase):
    def test_numeric_change_is_material_even_with_tiny_embedding_shift(self):
        sev, sem, nums, _ = classify_change("refund within 30 days", "refund within 14 days")
        self.assertEqual(sev, "material")
        self.assertEqual(nums, ["30 -> 14"])

    def test_whitespace_only_change_has_same_hash(self):
        self.assertEqual(V1["api-limits#rate-limits"].content_hash, V2["api-limits#rate-limits"].content_hash)

    def test_diff_detects_add_remove_and_typo(self):
        kinds = {c.chunk_id: (c.kind, c.severity) for c in diff(V1, V2)}
        self.assertEqual(kinds["legacy-export#csv-export"][0], "removed")
        self.assertEqual(kinds["data-export#export-api"][0], "added")
        self.assertEqual(kinds["refunds#how-to-request"][1], "cosmetic")

    def test_incremental_rebuild_fixes_stale_answers_without_full_reembed(self):
        deployed = build_index(V1)
        cand = incremental_rebuild(deployed, V2, diff(V1, V2))
        self.assertLess(cand.embed_calls, len(V2))
        probe = [{"id": "x", "question": "How many days do I have to get a refund on a monthly plan?", "fact_v2": "14 days", "traffic": 1}]
        r = run_probes(deployed, cand, probe)[0]
        self.assertTrue(r.deployed_stale)
        self.assertTrue(r.candidate_correct)

    def test_stale_review_sla(self):
        self.assertIn("sso", [d for d, _, _ in stale_docs(V2, date(2026, 11, 6))])

    def test_index_skips_unchanged_chunks(self):
        idx = VectorIndex()
        c = next(iter(V1.values()))
        idx.upsert(c)
        idx.upsert(c)
        self.assertEqual(idx.embed_calls, 1)


if __name__ == "__main__":
    unittest.main()
