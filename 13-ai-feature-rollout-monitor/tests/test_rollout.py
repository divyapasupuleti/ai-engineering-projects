import random
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from flags import in_treatment  # noqa: E402
from rollout import Observation, RolloutController  # noqa: E402
from simulate import SCENARIOS, run  # noqa: E402
from stats_tests import worse_proportion  # noqa: E402


def obs(arm, bad=False, safety=False, latency=1000.0):
    return Observation("u", arm, bad, False, latency, 0.004, False, safety, {"locale": "en", "plan": "free"})


class RolloutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctl = RolloutController("f", Path(self.tmp.name) / "audit.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_assignment_is_sticky_and_monotonic(self):
        users = [f"u{i}" for i in range(5000)]
        at5 = {u for u in users if in_treatment(u, "feat", 5)}
        at25 = {u for u in users if in_treatment(u, "feat", 25)}
        self.assertTrue(at5 <= at25)
        self.assertAlmostEqual(len(at25) / len(users), 0.25, delta=0.03)

    def test_z_test_direction(self):
        self.assertLess(worse_proportion(80, 1000, 140, 1000).p_value, 0.001)
        self.assertGreater(worse_proportion(80, 1000, 60, 1000).p_value, 0.5)

    def test_hold_until_enough_samples(self):
        for _ in range(100):
            self.ctl.record(obs("treatment"))
        self.assertEqual(self.ctl.evaluate().action, "hold")

    def test_safety_rollback(self):
        for i in range(300):
            self.ctl.record(obs("treatment", safety=i < 3))
        self.assertEqual(self.ctl.evaluate().action, "rollback")
        self.assertEqual(self.ctl.percent, 0)

    def test_latency_pause_and_audit(self):
        rng = random.Random(1)
        for _ in range(600):
            self.ctl.record(obs("control", latency=rng.uniform(900, 1100)))
            self.ctl.record(obs("treatment", latency=rng.uniform(1500, 1700)))
        self.assertEqual(self.ctl.evaluate().action, "pause")
        self.assertIn('"action": "pause"', (Path(self.tmp.name) / "audit.jsonl").read_text())

    def test_segment_regression_caught_before_full_rollout(self):
        ctl = run("segment_regression", SCENARIOS["segment_regression"])
        self.assertEqual(ctl.state, "rolled_back")
        self.assertLessEqual(ctl.stage_idx, 2)


if __name__ == "__main__":
    unittest.main()
