"""LLM spend gateway: classify -> route -> pre-call budget check -> call -> log -> verify sample."""

from __future__ import annotations

import random
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from classifier import classify  # noqa: E402
from common.io import read_json  # noqa: E402
from common.pricing import MODELS, cost_usd  # noqa: E402
from common.text import count_tokens  # noqa: E402
from providers import SimulatedProvider, is_acceptable  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY, ts REAL, day TEXT, team TEXT, feature TEXT, priority TEXT, tier INTEGER,
  model TEXT, input_tokens INTEGER, output_tokens INTEGER, latency_ms REAL, cost_usd REAL,
  status TEXT, escalated INTEGER DEFAULT 0, over_budget INTEGER DEFAULT 0, reasons TEXT
);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, ts REAL, day TEXT, team TEXT, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY, request_id INTEGER, model TEXT, better_model TEXT, passed INTEGER, reason TEXT
);
"""


class BudgetExceeded(Exception):
    pass


@dataclass
class GatewayRequest:
    team: str
    feature: str
    prompt: str
    priority: str = "normal"
    risk_tags: list[str] = field(default_factory=list)
    output_format: str = "text"
    model_preference: str | None = None
    difficulty: int | None = None
    day: str = "2026-11-01"


@dataclass
class GatewayResponse:
    request_id: int
    model: str
    tier: int
    cost_usd: float
    latency_ms: float
    escalated: bool
    over_budget: bool
    warnings: list[str]


class SpendGateway:
    def __init__(self, db_path: str = ":memory:", config_dir: Path = ROOT / "config", seed: int = 11) -> None:
        self.db = sqlite3.connect(db_path)
        self.db.executescript(SCHEMA)
        self.routing = read_json(config_dir / "routing.json")
        self.budgets = read_json(config_dir / "budgets.json")
        self.provider = SimulatedProvider()
        self.rng = random.Random(seed)
        self._alerted: set[tuple[str, str, str]] = set()

    def spend(self, team: str, day: str | None = None) -> float:
        if day:
            q = "SELECT COALESCE(SUM(cost_usd),0) FROM requests WHERE team=? AND day=?"
            return self.db.execute(q, (team, day)).fetchone()[0]
        return self.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM requests WHERE team=?", (team,)).fetchone()[0]

    def choose_model(self, req: GatewayRequest, tier: int) -> str:
        if req.feature in self.routing["feature_overrides"]:
            return self.routing["feature_overrides"][req.feature]
        if req.model_preference in MODELS:
            return req.model_preference
        return self.routing["tiers"][str(tier)]

    def _alert(self, req: GatewayRequest, level: str, msg: str) -> None:
        key = (req.team, req.day, level)
        if key not in self._alerted:
            self._alerted.add(key)
            self.db.execute("INSERT INTO alerts(ts, day, team, level, message) VALUES (?,?,?,?,?)", (time.time(), req.day, req.team, level, msg))

    def check_budget(self, req: GatewayRequest, model: str) -> tuple[bool, list[str]]:
        limit = self.budgets[req.team]["daily_usd"]
        estimate = cost_usd(model, count_tokens(req.prompt), 300)
        spent = self.spend(req.team, req.day)
        warnings = []
        if spent + estimate >= limit:
            if req.priority == "low":
                self._alert(req, "block", f"{req.team} hit 100% of daily budget; blocking low-priority requests")
                raise BudgetExceeded(f"{req.team} daily budget ${limit:.2f} exhausted (spent ${spent:.4f})")
            self._alert(req, "over", f"{req.team} exceeded daily budget; serving {req.priority} requests with override")
            warnings.append("over_budget_override")
            return True, warnings
        if spent + estimate >= 0.8 * limit:
            self._alert(req, "warn", f"{req.team} at 80% of daily budget")
            warnings.append("budget_80pct")
        return False, warnings

    def handle(self, req: GatewayRequest) -> GatewayResponse:
        cls = classify(req.prompt, req.risk_tags, req.output_format)
        difficulty = req.difficulty or cls.tier
        model = self.choose_model(req, cls.tier)
        try:
            over_budget, warnings = self.check_budget(req, model)
        except BudgetExceeded as exc:
            self.db.execute(
                "INSERT INTO requests(ts, day, team, feature, priority, tier, model, input_tokens, output_tokens, latency_ms, cost_usd, status, reasons) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), req.day, req.team, req.feature, req.priority, cls.tier, model, 0, 0, 0, 0, "blocked", str(exc)),
            )
            raise
        resp = self.provider.complete(model, req.prompt, difficulty)
        escalated = False
        total_cost, total_latency = resp.cost_usd, resp.latency_ms
        if req.priority in self.routing["escalate_priorities"] and resp.confidence < 0.7 and model != self.routing["strong_model"]:
            strong = self.provider.complete(self.routing["strong_model"], req.prompt, difficulty)
            escalated, model = True, strong.model
            total_cost += strong.cost_usd
            total_latency += strong.latency_ms
            resp = strong
        cur = self.db.execute(
            "INSERT INTO requests(ts, day, team, feature, priority, tier, model, input_tokens, output_tokens, latency_ms, cost_usd, status, escalated, over_budget, reasons) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), req.day, req.team, req.feature, req.priority, cls.tier, model, resp.input_tokens, resp.output_tokens,
             total_latency, total_cost, "ok", int(escalated), int(over_budget), "; ".join(cls.reasons)),
        )
        rid = cur.lastrowid
        if model != self.routing["strong_model"] and self.rng.random() < self.routing["verification_sample_rate"]:
            self.verify(rid, model, req.prompt, difficulty)
        return GatewayResponse(rid, model, cls.tier, round(total_cost, 6), round(total_latency, 1), escalated, over_budget, warnings)

    def verify(self, request_id: int, model: str, prompt: str, difficulty: int) -> bool:
        """Async in production (Celery/RQ); compares the routed answer against the strong model."""
        passed = is_acceptable(model, difficulty, prompt)
        reason = "ok" if passed else f"{model} below quality bar for difficulty {difficulty}"
        self.db.execute(
            "INSERT INTO verifications(request_id, model, better_model, passed, reason) VALUES (?,?,?,?,?)",
            (request_id, model, self.routing["strong_model"], int(passed), reason),
        )
        return passed
