import socket
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "gpu"))

import matrix  # noqa: E402
import report  # noqa: E402
import vllm_bench  # noqa: E402

FAKE = str(HERE / "fake_vllm.py")
SMALL = ["--concurrency", "1,8", "--requests", "8", "--max-tokens", "16", "--input-words", "20",
         "--metrics-interval", "0.02"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_fake(config: dict, out_dir: Path, extra_flags: list[str] | None = None) -> dict:
    cfg = matrix.load()
    cfg["server"] = {**cfg["server"], "port": free_port(), "ready_timeout_s": 30}
    cmd = [sys.executable, FAKE, *matrix.server_args(config, cfg["server"]), *(extra_flags or [])]
    return matrix.run_one(config, cfg, cmd, out_dir / f"{config['label']}.json", 0.8, out_dir / "logs")


class TestParsing(unittest.TestCase):
    def test_prometheus_sums_labelled_series_and_skips_comments(self):
        text = "# HELP x\nvllm:num_requests_waiting{a=\"1\"} 2\nvllm:num_requests_waiting{a=\"2\"} 3\nbad line\n"
        self.assertEqual(vllm_bench.parse_prometheus(text), {"vllm:num_requests_waiting": 5.0})

    def test_select_by_group_and_rejects_unknown(self):
        cfg = matrix.load()
        self.assertEqual({c["group"] for c in matrix.select(cfg, "precision")}, {"precision"})
        with self.assertRaises(SystemExit):
            matrix.select(cfg, "no-such-config")

    def test_docker_command_requests_gpus_and_model(self):
        cfg = matrix.load()
        cmd = matrix.docker_command(cfg["configs"][1], cfg["server"], "n", "/cache", "tok")
        self.assertIn("--gpus", cmd)
        self.assertIn("HF_TOKEN=tok", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "Qwen/Qwen2.5-7B-Instruct")
        self.assertIn("fp8", cmd)


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        base = {"model": "fake/Qwen-7B", "args": [], "bench_args": SMALL}
        cls.bf16 = run_fake({**base, "label": "fake-bf16", "group": "precision", "description": "baseline"}, out)
        cls.on = run_fake({**base, "label": "fake-prefix-cache-on", "group": "prefix-caching", "description": "on"},
                          out, ["--fake-prefix-hits"])
        cls.off = run_fake({**base, "label": "fake-prefix-cache-off", "group": "prefix-caching", "description": "off"}, out)
        cls.summary = report.build(out)
        cls.md = (out / "GPU_BENCHMARK.md").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_streams_measured_with_server_usage(self):
        lv = self.bf16["levels"][0]
        self.assertEqual(lv["failed"], 0)
        self.assertEqual(lv["mean_output_tokens"], 16)
        self.assertGreater(lv["ttft_ms"]["p50"], 5)
        self.assertGreater(lv["output_tokens_per_s"], 0)
        self.assertEqual(self.bf16["vllm_version"], "0.0-fake")
        self.assertEqual(lv["usd_per_1m_output_tokens"], round(0.8 / (lv["output_tokens_per_s"] * 3600) * 1e6, 3))

    def test_vllm_metrics_sampled(self):
        busy = self.bf16["levels"][1]
        self.assertIsNotNone(busy["kv_cache_peak_pct"])
        self.assertGreater(busy["kv_cache_peak_pct"], 0)
        self.assertGreater(busy["queued_peak"], 0)
        self.assertAlmostEqual(self.on["levels"][1]["prefix_cache_hit_rate"], 0.5, delta=0.05)
        self.assertEqual(self.off["levels"][1]["prefix_cache_hit_rate"], 0.0)

    def test_report_has_summary_prefix_table_and_cv_lines(self):
        self.assertIn("GPU_BENCHMARK.md", self.summary)
        self.assertIn("| `fake-bf16` |", self.md)
        self.assertIn("## Prefix caching", self.md)
        self.assertIn("**Recommendation:** `fake-bf16`", self.md)
        self.assertIn("## CV / LinkedIn lines", self.md)


if __name__ == "__main__":
    unittest.main()
