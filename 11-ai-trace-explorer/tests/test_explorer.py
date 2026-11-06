import random
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT))

from analyzer import analyse, self_time  # noqa: E402
from explorer import simulate  # noqa: E402
from trace_store import SimClock, TraceRecorder, TraceStore  # noqa: E402


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TraceStore(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_spans_nest_and_persist(self):
        clock = SimClock()
        rec = TraceRecorder(clock)
        with rec.span("request"):
            with rec.span("child"):
                clock.advance(10)
        self.store.save(rec, {"feature": "f", "prompt_version": "v", "model": "m", "user_input": "q"})
        spans = self.store.spans(rec.trace_id)
        child = next(s for s in spans if s["name"] == "child")
        root = next(s for s in spans if s["name"] == "request")
        self.assertEqual(child["parent_id"], root["span_id"])
        self.assertEqual(self_time(spans)["request"], 0)

    def test_classifier_finds_injected_faults(self):
        simulate(self.store, 120)
        for t in self.store.traces():
            spans = self.store.spans(t["trace_id"])
            fault = next(s for s in spans if s["parent_id"] is None)["attrs"]["injected_fault"]
            cats = {f.category for f in analyse(spans)}
            if fault == "schema_invalid":
                self.assertIn("schema_invalid", cats)
            if fault == "llm_timeout":
                self.assertIn("llm_timeout", cats)
            if fault == "none":
                self.assertEqual(cats, set())

    def test_error_propagates_to_root(self):
        clock = SimClock()
        rec = TraceRecorder(clock)
        with self.assertRaises(RuntimeError):
            with rec.span("request"):
                with rec.span("tool.x"):
                    raise RuntimeError("503")
        self.assertTrue(all(s.status == "error" for s in rec.spans))


if __name__ == "__main__":
    unittest.main()
