"""Model backends: real Ollama over HTTP when available, otherwise a profile-driven simulator."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
TIME_SCALE = float(os.environ.get("SIM_TIME_SCALE", "1.0"))


class BackendError(Exception):
    pass


@dataclass
class Generation:
    text: str
    prompt_tokens: int
    completion_tokens: int
    ttft_ms: float
    total_ms: float


def ollama_available(timeout: float = 0.3) -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


class OllamaBackend:
    def __init__(self, name: str, profile: dict) -> None:
        self.name, self.profile = name, profile

    def generate(self, messages: list[dict], max_tokens: int) -> Generation:
        body = json.dumps({"model": self.profile["ollama_tag"], "messages": messages, "stream": False,
                           "options": {"num_predict": max_tokens}}).encode()
        start = time.perf_counter()
        try:
            resp = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"{OLLAMA_URL}/api/chat", body, {"Content-Type": "application/json"}), timeout=120).read())
        except (urllib.error.URLError, OSError) as exc:
            raise BackendError(f"ollama error: {exc}") from exc
        total = (time.perf_counter() - start) * 1000
        return Generation(resp["message"]["content"], resp.get("prompt_eval_count", 0), resp.get("eval_count", 0),
                          resp.get("prompt_eval_duration", 0) / 1e6, total)

    def stream(self, messages: list[dict], max_tokens: int) -> Iterator[str]:
        yield self.generate(messages, max_tokens).text


class SimulatedBackend:
    """Behaves like a quantised local model: TTFT, tokens/s and a fixed number of parallel slots."""

    def __init__(self, name: str, profile: dict) -> None:
        self.name, self.profile = name, profile
        self.slots = threading.Semaphore(profile["max_parallel"])

    def _tokens(self, messages: list[dict], max_tokens: int) -> list[str]:
        prompt = messages[-1]["content"]
        words = f"Local answer from {self.name}: {prompt}".split()
        n = min(max_tokens, 24 + len(prompt) % 40)
        return [words[i % len(words)] for i in range(n)]

    def generate(self, messages: list[dict], max_tokens: int) -> Generation:
        if self.profile.get("fail"):
            raise BackendError(f"model {self.name} failed to load")
        start = time.perf_counter()
        with self.slots:
            queued = (time.perf_counter() - start) * 1000
            toks = self._tokens(messages, max_tokens)
            ttft = self.profile["ttft_ms"]
            gen_ms = len(toks) / self.profile["tokens_per_s"] * 1000
            time.sleep((ttft + gen_ms) / 1000 * TIME_SCALE)
        total = (time.perf_counter() - start) * 1000 / TIME_SCALE
        prompt_tokens = sum(len(m["content"]) for m in messages) // 4
        return Generation(" ".join(toks), prompt_tokens, len(toks), queued / TIME_SCALE + ttft, total)

    def stream(self, messages: list[dict], max_tokens: int) -> Iterator[str]:
        if self.profile.get("fail"):
            raise BackendError(f"model {self.name} failed to load")
        with self.slots:
            time.sleep(self.profile["ttft_ms"] / 1000 * TIME_SCALE)
            for t in self._tokens(messages, max_tokens):
                time.sleep(1 / self.profile["tokens_per_s"] * TIME_SCALE)
                yield t + " "


def make_backend(name: str, profile: dict, prefer_ollama: bool = True):
    if prefer_ollama and not profile.get("fail") and ollama_available():
        return OllamaBackend(name, profile)
    return SimulatedBackend(name, profile)
