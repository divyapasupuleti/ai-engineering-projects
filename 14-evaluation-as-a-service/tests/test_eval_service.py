import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from calibration import cohen_kappa, spearman, tune_threshold  # noqa: E402
from generate_data import generate  # noqa: E402
from judges import JUDGES, load_rubric  # noqa: E402
from server import serve  # noqa: E402
from service import EvalService  # noqa: E402

RUBRIC = PROJECT / "rubrics" / "support_answer.v2.json"


class EvalServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = EvalService(Path(self.tmp.name) / "e.db", RUBRIC)

    def tearDown(self):
        self.svc.db.close()
        self.tmp.cleanup()

    def test_metrics(self):
        self.assertEqual(cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertEqual(tune_threshold([5, 5, 4, 2], [5, 4.5, 3, 2], 4)[0], 5)

    def test_judge_rewards_facts_and_citation(self):
        rubric = load_rubric(RUBRIC)
        item = {"key_facts": ["14 days", "original card"]}
        good = JUDGES["judge-large"].judge(rubric, item, "Refunds within 14 days to the original card. [kb:refund]", "g")
        bad = JUDGES["judge-large"].judge(rubric, item, "Refunds are always instant.", "b")
        self.assertGreater(good.score, bad.score)
        self.assertEqual(bad.criteria["no_unsupported_claims"], 0.0)

    def test_gate_blocks_category_regression(self):
        data = generate()
        rb = self.svc.evaluate(data, "judge-large", 4, "v1")
        rc = self.svc.evaluate(data, "judge-large", 4, "v2")
        verdict, reasons = self.svc.gate(rb, rc)
        self.assertEqual(verdict, "BLOCK")
        self.assertTrue(any("refund" in r for r in reasons))
        self.assertEqual(self.svc.gate(rb, rb)[0], "PASS")

    def test_http_evaluate(self):
        srv = serve(self.svc, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        body = json.dumps({"items": [{"id": "a", "key_facts": ["x"], "output": "x [kb:a]"}]}).encode()
        resp = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/evaluate", body, {"Content-Type": "application/json"}), timeout=5).read())
        self.assertEqual(resp["n"], 1)
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    unittest.main()
