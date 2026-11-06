"""Minimal OpenTelemetry-shaped tracer: one trace id, nested spans, attributes."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Span:
    trace_id: str
    span_id: str
    name: str
    start_ms: float
    end_ms: float = 0.0
    status: str = "ok"
    error: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return round(self.end_ms - self.start_ms, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "attrs": self.attrs,
        }


class Tracer:
    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Span]:
        s = Span(self.trace_id, uuid.uuid4().hex[:8], name, time.perf_counter() * 1000, attrs=dict(attrs))
        try:
            yield s
        except Exception as exc:
            s.status = "error"
            s.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            s.end_ms = time.perf_counter() * 1000
            self.spans.append(s)
