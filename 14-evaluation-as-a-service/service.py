"""Evaluation service: batch runs persisted in SQLite, run comparison and a release gate."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from judges import JUDGES, load_rubric

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, created REAL, system_version TEXT, rubric TEXT,
  rubric_version TEXT, judge TEXT, judge_pass_at INTEGER, n INTEGER, mean_score REAL, pass_rate REAL, cost REAL);
CREATE TABLE IF NOT EXISTS results (run_id TEXT, item_id TEXT, category TEXT, score INTEGER, passed INTEGER,
  criteria TEXT, rationale TEXT);
"""


@dataclass
class GatePolicy:
    min_pass_rate: float = 0.45
    max_pass_rate_drop: float = 0.03
    max_category_drop: float = 0.10


class EvalService:
    def __init__(self, db_path: Path, rubric_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.rubric = load_rubric(rubric_path)

    def evaluate(self, items: list[dict], judge: str, judge_pass_at: int, system_version: str) -> str:
        j = JUDGES[judge]
        run_id = uuid.uuid4().hex[:10]
        rows, cost = [], 0.0
        for it in items:
            out = it["outputs"][system_version] if "outputs" in it else it["output"]
            jd = j.judge(self.rubric, it, out, f"{it['id']}:{system_version}")
            cost += jd.cost
            rows.append((run_id, it["id"], it.get("category", "all"), jd.score, int(jd.score >= judge_pass_at),
                         json.dumps(jd.criteria), jd.rationale))
        n = len(rows)
        self.db.executemany("INSERT INTO results VALUES (?,?,?,?,?,?,?)", rows)
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            run_id, time.time(), system_version, self.rubric["id"], self.rubric["version"], judge, judge_pass_at, n,
            sum(r[3] for r in rows) / n, sum(r[4] for r in rows) / n, cost))
        self.db.commit()
        return run_id

    def run(self, run_id: str) -> dict:
        return dict(self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())

    def runs(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY created")]

    def by_category(self, run_id: str) -> dict[str, float]:
        out = defaultdict(list)
        for r in self.db.execute("SELECT category, passed FROM results WHERE run_id=?", (run_id,)):
            out[r["category"]].append(r["passed"])
        return {k: sum(v) / len(v) for k, v in sorted(out.items())}

    def compare(self, baseline: str, candidate: str) -> dict:
        b = {r["item_id"]: r["score"] for r in self.db.execute("SELECT item_id, score FROM results WHERE run_id=?", (baseline,))}
        c = {r["item_id"]: r["score"] for r in self.db.execute("SELECT item_id, score FROM results WHERE run_id=?", (candidate,))}
        common = b.keys() & c.keys()
        return {"improved": sum(c[i] > b[i] for i in common), "regressed": sum(c[i] < b[i] for i in common),
                "unchanged": sum(c[i] == b[i] for i in common),
                "worst": sorted(common, key=lambda i: c[i] - b[i])[:3]}

    def gate(self, baseline: str, candidate: str, policy: GatePolicy = GatePolicy()) -> tuple[str, list[str]]:
        rb, rc = self.run(baseline), self.run(candidate)
        reasons = []
        if rc["pass_rate"] < policy.min_pass_rate:
            reasons.append(f"pass rate {rc['pass_rate']:.1%} < {policy.min_pass_rate:.0%}")
        if rb["pass_rate"] - rc["pass_rate"] > policy.max_pass_rate_drop:
            reasons.append(f"pass rate dropped {rb['pass_rate'] - rc['pass_rate']:.1%}")
        cb, cc = self.by_category(baseline), self.by_category(candidate)
        for cat in cb:
            drop = cb[cat] - cc.get(cat, 0)
            if drop > policy.max_category_drop:
                reasons.append(f"category '{cat}' pass rate {cb[cat]:.0%} -> {cc.get(cat, 0):.0%}")
        return ("BLOCK" if reasons else "PASS"), reasons
