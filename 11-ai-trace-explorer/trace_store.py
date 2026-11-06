"""OpenTelemetry-shaped spans (trace_id, span_id, parent_id, attributes) persisted to SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
  trace_id TEXT PRIMARY KEY, started_ms REAL, duration_ms REAL, status TEXT,
  feature TEXT, prompt_version TEXT, model TEXT, user_input TEXT, output TEXT
);
CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY, trace_id TEXT, parent_id TEXT, name TEXT,
  start_ms REAL, end_ms REAL, status TEXT, error TEXT, attrs TEXT
);
CREATE INDEX IF NOT EXISTS spans_trace ON spans(trace_id);
"""


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start_ms: float
    end_ms: float = 0.0
    status: str = "ok"
    error: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return round(self.end_ms - self.start_ms, 2)


class SimClock:
    """Simulated milliseconds so 300 traces with 4-second LLM calls run instantly and deterministically."""

    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, ms: float) -> None:
        self.now += ms


class TraceRecorder:
    def __init__(self, clock: SimClock, trace_id: str | None = None) -> None:
        self.clock = clock
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self.spans: list[Span] = []
        self._stack: list[str] = []

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Span]:
        s = Span(self.trace_id, uuid.uuid4().hex[:8], self._stack[-1] if self._stack else None, name,
                 self.clock.now, attrs=dict(attrs))
        self._stack.append(s.span_id)
        try:
            yield s
        except Exception as exc:
            s.status, s.error = "error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            s.end_ms = self.clock.now
            self._stack.pop()
            self.spans.append(s)


class TraceStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def reset(self) -> None:
        self.db.executescript("DELETE FROM traces; DELETE FROM spans;")

    def save(self, rec: TraceRecorder, meta: dict[str, Any]) -> None:
        root = next(s for s in rec.spans if s.parent_id is None)
        self.db.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?)",
            (rec.trace_id, root.start_ms, root.duration_ms, root.status, meta["feature"], meta["prompt_version"],
             meta["model"], meta["user_input"], meta.get("output", "")),
        )
        self.db.executemany(
            "INSERT INTO spans VALUES (?,?,?,?,?,?,?,?,?)",
            [(s.span_id, s.trace_id, s.parent_id, s.name, s.start_ms, s.end_ms, s.status, s.error,
              json.dumps(s.attrs)) for s in rec.spans],
        )
        self.db.commit()

    def traces(self, where: str = "1=1", params: tuple = ()) -> list[sqlite3.Row]:
        return self.db.execute(f"SELECT * FROM traces WHERE {where} ORDER BY started_ms", params).fetchall()

    def spans(self, trace_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM spans WHERE trace_id=? ORDER BY start_ms, end_ms DESC", (trace_id,)).fetchall()
        return [{**dict(r), "attrs": json.loads(r["attrs"]), "duration_ms": round(r["end_ms"] - r["start_ms"], 2)} for r in rows]

    def span_durations(self) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for r in self.db.execute("SELECT name, end_ms - start_ms AS d FROM spans"):
            out.setdefault(r["name"], []).append(r["d"])
        return out
