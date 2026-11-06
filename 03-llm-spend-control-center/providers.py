"""Provider adapters normalised to one response schema.

`SimulatedProvider` uses the shared registry prices/latency and a seeded quality model so the
gateway can be exercised offline. Real adapters implement the same `complete` signature.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.pricing import MODELS, cost_usd, latency_ms  # noqa: E402
from common.text import count_tokens  # noqa: E402

REQUIRED_QUALITY = {1: 0.62, 2: 0.76, 3: 0.88}


@dataclass
class ProviderResponse:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    confidence: float


class SimulatedProvider:
    def complete(self, model: str, prompt: str, difficulty: int, max_output_tokens: int = 300) -> ProviderResponse:
        info = MODELS[model]
        in_tok = count_tokens(prompt)
        out_tok = min(max_output_tokens, 40 + difficulty * 60)
        jitter = int(hashlib.md5(f"{model}|{prompt}".encode()).hexdigest()[:4], 16) / 0xFFFF * 0.12 - 0.06
        confidence = max(0.0, min(1.0, info.quality - REQUIRED_QUALITY[difficulty] + 0.7 + jitter))
        return ProviderResponse(
            text=f"[{model}] response",
            model=model,
            provider=info.provider,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms(model, out_tok),
            cost_usd=cost_usd(model, in_tok, out_tok),
            confidence=round(confidence, 3),
        )


def is_acceptable(model: str, difficulty: int, prompt: str) -> bool:
    """Ground-truth quality oracle used by the async verifier in simulation."""
    jitter = int(hashlib.md5(f"q|{model}|{prompt}".encode()).hexdigest()[:4], 16) / 0xFFFF * 0.1 - 0.05
    return MODELS[model].quality + jitter >= REQUIRED_QUALITY[difficulty]
