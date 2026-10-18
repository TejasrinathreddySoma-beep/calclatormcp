"""MCP server. Tools go through: safety policy -> audit log -> async job queue -> swappable backend.

Run:  mcpcalc-server                       (stdio, spawned by the chat client)
      mcpcalc-server --transport streamable-http --port 8765     (HTTP, many clients at once)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from .backends import EvalError, get_backend
from .config import load_config
from .db import Database
from .executors import ExecResult, LocalExecutor
from .jobqueue import JobQueue, QueueFull
from .safety import policy_from_config


def build_server(cfg: dict) -> FastMCP:
    backend = get_backend(cfg)
    policy = policy_from_config(cfg)
    db = Database(cfg["database"]["path"])
    executor = LocalExecutor(backend, policy, db, source="mcp")
    s = cfg["server"]
    workers = 1 if getattr(backend, "blocking_ui", False) else int(s["workers"])
    queue = JobQueue(executor.evaluate, workers=workers, maxsize=int(s["queue_size"]), timeout=float(s["timeout_s"]))
    mcp = FastMCP("mcpcalc", host=s["host"], port=int(s["port"]))
    mcp.state = SimpleNamespace(backend=backend, policy=policy, db=db, executor=executor, queue=queue)

    @mcp.tool()
    async def evaluate(expression: str, dry_run: bool = False) -> str:
        """Evaluate a math expression and return JSON: {status, value, error, exec_ms, functions}.

        Supports + - * / ^ %, parentheses, pi, e and functions such as sqrt, cbrt, square, cube, recip, abs,
        factorial, ln, log, log(x,base), root(x,y), floor, ceil, sin/cos/tan (degrees by default), asin, sinh, ...
        status is ok | blocked (rejected by the safety policy) | error | dry_run (validated, not executed).
        """
        try:
            result = await queue.submit(expression, dry_run)
        except QueueFull as ex:
            result = ExecResult("error", error=str(ex))
        except asyncio.TimeoutError:
            result = ExecResult("error", error=f"timed out after {s['timeout_s']} s")
        return result.to_json()

    @mcp.tool()
    def set_angle_mode(mode: str) -> str:
        """Set the angle unit used by trig functions: 'deg', 'rad' or 'grad'."""
        try:
            return backend.set_angle_mode(mode)
        except EvalError as ex:
            return f"Error: {ex}"

    @mcp.tool()
    def list_functions() -> str:
        """List the supported function names (JSON array)."""
        return json.dumps(sorted(policy.allowed_functions))

    @mcp.tool()
    def server_stats() -> str:
        """Aggregate statistics from the request log: counts, success rate, p50/p95 latency, queue depth."""
        stats = db.stats()
        stats.update(queue_depth=queue.depth, backend=backend.name)
        return json.dumps(stats)

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="mcpcalc MCP server")
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"])
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--db", help="SQLite database path")
    parser.add_argument("--backend", choices=["python", "windows_calculator"])
    parser.add_argument("--dry-run", action="store_true", help="validate and log, never execute")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.transport:
        cfg["server"]["transport"] = args.transport
    if args.host:
        cfg["server"]["host"] = args.host
    if args.port:
        cfg["server"]["port"] = args.port
    if args.db:
        cfg["database"]["path"] = args.db
    if args.backend:
        cfg["backend"] = args.backend
    if args.dry_run:
        cfg["safety"]["dry_run"] = True

    logging.basicConfig(level=logging.WARNING)
    build_server(cfg).run(transport=cfg["server"]["transport"])


if __name__ == "__main__":
    main()
