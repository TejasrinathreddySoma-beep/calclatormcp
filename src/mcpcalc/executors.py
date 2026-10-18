"""Executors turn a validated expression into a number. Local (in-process) and MCP (over a session)."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field

from .backends.python_backend import EvalError
from .safety import Policy, SafetyError, validate


@dataclass
class ExecResult:
    status: str  # ok | blocked | error | dry_run
    value: float | None = None
    error: str = ""
    exec_ms: float = 0.0
    functions: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> ExecResult:
        return cls(**json.loads(text))


class LocalExecutor:
    """Safety check -> audit log -> backend. Used by the MCP server and directly by the benchmark."""

    def __init__(self, backend, policy: Policy, db=None, source: str = "local"):
        self.backend, self.policy, self.db, self.source = backend, policy, db, source

    def _audit(self, expression: str, decision: str, reason: str = "") -> None:
        if self.db is not None:
            self.db.log_audit(self.source, "evaluate", expression, decision, reason)

    async def evaluate(self, expression: str, dry_run: bool | None = None) -> ExecResult:
        try:
            functions = validate(expression, self.policy)
        except SafetyError as ex:
            self._audit(expression, "blocked", str(ex))
            return ExecResult("blocked", error=str(ex))
        if self.policy.dry_run or dry_run:
            self._audit(expression, "dry_run", "validated, not executed")
            return ExecResult("dry_run", functions=functions)
        self._audit(expression, "allowed")
        started = time.perf_counter()
        try:
            if getattr(self.backend, "blocking_ui", False):
                value = self.backend.evaluate(expression)
            else:
                value = await asyncio.to_thread(self.backend.evaluate, expression)
        except EvalError as ex:
            return ExecResult("error", error=str(ex), exec_ms=(time.perf_counter() - started) * 1000,
                              functions=functions)
        except Exception as ex:  # backend bug or UI failure: report, never crash the server
            return ExecResult("error", error=f"{type(ex).__name__}: {ex}",
                              exec_ms=(time.perf_counter() - started) * 1000, functions=functions)
        return ExecResult("ok", value=value, exec_ms=(time.perf_counter() - started) * 1000, functions=functions)


class McpExecutor:
    """Calls the `evaluate` tool of a running MCP server (stdio or HTTP)."""

    def __init__(self, session, dry_run: bool = False):
        self.session, self.dry_run = session, dry_run

    async def evaluate(self, expression: str, dry_run: bool | None = None) -> ExecResult:
        result = await self.session.call_tool(
            "evaluate", {"expression": expression, "dry_run": self.dry_run if dry_run is None else dry_run})
        text = "\n".join(c.text for c in result.content if c.type == "text")
        if result.isError:
            return ExecResult("error", error=text)
        try:
            return ExecResult.from_json(text)
        except (json.JSONDecodeError, TypeError):
            return ExecResult("error", error=f"unexpected server reply: {text[:200]}")
