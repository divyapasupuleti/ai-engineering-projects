import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["SIM_TIME_SCALE"] = "0.01"
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from llm_server import build_server  # noqa: E402

KEY = {"Authorization": "Bearer local-dev-key", "Content-Type": "application/json"}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.mgr, _ = build_server(0, prefer_ollama=False)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def post(self, path, body, headers=KEY):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_openai_compatible_response(self):
        code, body = self.post("/v1/chat/completions", {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 5})
        self.assertEqual(code, 200)
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["choices"][0]["message"]["role"], "assistant")
        self.assertLessEqual(body["usage"]["completion_tokens"], 5)

    def test_auth_required(self):
        code, _ = self.post("/v1/chat/completions", {"messages": []}, {"Authorization": "Bearer nope"})
        self.assertEqual(code, 401)

    def test_switch_guards_and_rollback(self):
        code, body = self.post("/admin/switch", {"model": "llama3.1-8b:fp16"})
        self.assertEqual(code, 409)
        code, _ = self.post("/admin/switch", {"model": "broken-model:q4"})
        self.assertEqual(code, 409)
        start = self.mgr.active
        self.assertEqual(self.post("/admin/switch", {"model": "qwen2.5-3b:q4_K_M"})[0], 200)
        self.assertEqual(self.post("/admin/rollback", {})[0], 200)
        self.assertEqual(self.mgr.active, start)

    def test_metrics_exposed(self):
        self.post("/v1/chat/completions", {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 3})
        text = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/metrics", timeout=5).read().decode()
        self.assertIn("llm_requests_total", text)
        self.assertIn("llm_request_seconds_bucket", text)


if __name__ == "__main__":
    unittest.main()
