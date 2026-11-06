"""Model registry with illustrative per-1K-token prices and latency profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    provider: str
    tier: int
    input_per_1k: float
    output_per_1k: float
    base_latency_ms: float
    ms_per_output_token: float
    quality: float
    max_context: int = 128_000


MODELS: dict[str, ModelInfo] = {
    m.name: m
    for m in [
        ModelInfo("local-llama-8b", "ollama", 1, 0.0, 0.0, 120, 18, 0.70, 8_192),
        ModelInfo("gpt-4o-mini", "openai", 1, 0.00015, 0.0006, 350, 8, 0.80),
        ModelInfo("claude-haiku", "anthropic", 2, 0.0008, 0.004, 400, 7, 0.84),
        ModelInfo("gpt-4o", "openai", 3, 0.0025, 0.01, 700, 12, 0.92),
        ModelInfo("claude-sonnet", "anthropic", 3, 0.003, 0.015, 800, 11, 0.94),
    ]
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    m = MODELS[model]
    return input_tokens / 1000 * m.input_per_1k + output_tokens / 1000 * m.output_per_1k


def latency_ms(model: str, output_tokens: int) -> float:
    m = MODELS[model]
    return m.base_latency_ms + m.ms_per_output_token * output_tokens
