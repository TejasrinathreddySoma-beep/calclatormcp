"""SQLite persistence: every request (with timings) and every safety decision (audit log)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    session TEXT, user_text TEXT, normalized_text TEXT,
    model TEXT, strategy TEXT, backend TEXT,
    expression TEXT, result REAL, status TEXT, error TEXT,
    retries INTEGER DEFAULT 0, llm_ms REAL, exec_ms REAL, total_ms REAL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT, tool TEXT, expression TEXT, decision TEXT, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""

_REQUEST_COLUMNS = ("session", "user_text", "normalized_text", "model", "strategy", "backend", "expression",
                    "result", "status", "error", "retries", "llm_ms", "exec_ms", "total_ms")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def log_request(self, **fields) -> int:
        values = [fields.get(col) for col in _REQUEST_COLUMNS]
        with self._conn() as conn:
            columns = ", ".join(_REQUEST_COLUMNS)
            marks = ", ".join("?" * (len(_REQUEST_COLUMNS) + 1))
            cur = conn.execute(f"INSERT INTO requests (ts, {columns}) VALUES ({marks})", [time.time(), *values])
            return int(cur.lastrowid)

    def log_audit(self, source: str, tool: str, expression: str, decision: str, reason: str = "") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO audit (ts, source, tool, expression, decision, reason) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), source, tool, expression, decision, reason))
            return int(cur.lastrowid)

    def recent_requests(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,))]

    def recent_audit(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]

    def stats(self) -> dict:
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT status, total_ms, llm_ms, exec_ms, retries FROM requests")]
            blocked = conn.execute("SELECT COUNT(*) FROM audit WHERE decision = 'blocked'").fetchone()[0]
        total = len(rows)
        ok = sum(1 for r in rows if r["status"] == "ok")
        totals = [r["total_ms"] for r in rows if r["total_ms"] is not None]
        return {
            "total_requests": total,
            "ok": ok,
            "success_rate": round(ok / total, 4) if total else 0.0,
            "blocked_by_policy": blocked,
            "p50_ms": round(_percentile(totals, 50), 1),
            "p95_ms": round(_percentile(totals, 95), 1),
            "avg_llm_ms": round(sum(r["llm_ms"] or 0 for r in rows) / total, 1) if total else 0.0,
            "avg_exec_ms": round(sum(r["exec_ms"] or 0 for r in rows) / total, 1) if total else 0.0,
            "avg_retries": round(sum(r["retries"] or 0 for r in rows) / total, 3) if total else 0.0,
        }
