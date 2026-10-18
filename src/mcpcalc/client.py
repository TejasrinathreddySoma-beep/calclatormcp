"""Interactive chat client: a local LLM translates English to an expression, the MCP server executes it."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import load_config
from .db import Database
from .executors import McpExecutor
from .llm import OllamaLLM
from .pipeline import Result, answer
from .translator import STRATEGIES, looks_like_math

HELP = """Ask in plain English:  10 pencils cost 5 each, total?  |  sin 90  |  5 times log 5 base 4  |  ceiling of 4.2
Commands:
  /dry               toggle dry-run (translate + validate, do not execute)
  /angle deg|rad|grad  set the trig angle unit
  /strategy <name>   baseline | prompt | rewrite | full
  /stats             request statistics from the log (p50/p95 latency, success rate, ...)
  /functions         list supported functions
  exit               quit"""


@asynccontextmanager
async def connect(url: str | None, config_path: str | None):
    if url:
        try:
            from mcp.client.streamable_http import streamable_http_client as http_client
        except ImportError:  # older mcp versions
            from mcp.client.streamable_http import streamablehttp_client as http_client
        async with http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session
    else:
        argv = ["-m", "mcpcalc.server"] + (["--config", config_path] if config_path else [])
        async with stdio_client(StdioServerParameters(command=sys.executable, args=argv)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def fmt(value: float) -> str:
    return f"{value:.10g}"


def show(res: Result) -> None:
    if res.status == "ok":
        print(f"calc> {fmt(res.value)}    [{res.expression}]")
    elif res.status == "dry_run":
        print(f"calc> (dry run) validated, not executed: {res.expression}")
    elif res.status == "blocked":
        print(f"calc> blocked by the safety policy: {res.error}    [{res.expression}]")
    else:
        print(f"calc> could not calculate: {res.error}    [{res.expression}]")


async def run(args) -> None:
    cfg = load_config(args.config)
    model = args.model or cfg["llm"]["model"]
    strategy = args.strategy or cfg["translator"]["strategy"]
    llm = OllamaLLM(model, cfg["llm"].get("host"), float(cfg["llm"].get("temperature", 0)))
    db = Database(cfg["database"]["path"])
    session_id = uuid.uuid4().hex[:8]
    history = [{"role": "system",
                "content": "You are a friendly assistant. Keep replies short. Do not do calculations."}]
    dry = False

    async with connect(args.url, args.config) as session:
        tools = [t.name for t in (await session.list_tools()).tools]
        stats = json.loads((await session.call_tool("server_stats", {})).content[0].text)
        backend_name = stats.get("backend", cfg["backend"])  # what the server really uses
        print(f"Connected ({'HTTP ' + args.url if args.url else 'stdio'}). Tools: {', '.join(tools)}")
        print(f"Model: {model} | strategy: {strategy} | backend: {backend_name}\n{HELP}")
        print("\nLoading the model into memory (the first start can take 20-30 s)...")
        try:
            print(f"Ready ({await llm.warm_up():.1f} s).")
        except Exception as ex:  # noqa: BLE001 - tell the user what to check, then carry on
            print(f"Could not reach Ollama ({type(ex).__name__}). Is `ollama serve` running and the model pulled?")

        while True:
            q = (await asyncio.to_thread(input, "\nyou> ")).strip()
            low = q.lower()
            if not q:
                continue
            if low in {"exit", "quit", "q"}:
                break
            if low in {"/help", "help"}:
                print(HELP)
            elif low == "/dry":
                dry = not dry
                print(f"calc> dry-run {'ON' if dry else 'OFF'}")
            elif low.startswith("/angle "):
                out = await session.call_tool("set_angle_mode", {"mode": q[7:].strip()})
                print("calc>", out.content[0].text)
            elif low.startswith("/strategy "):
                name = low[10:].strip()
                if name in STRATEGIES:
                    strategy = name
                    print(f"calc> strategy: {strategy}")
                else:
                    print(f"calc> choose one of: {', '.join(STRATEGIES)}")
            elif low == "/stats":
                out = await session.call_tool("server_stats", {})
                print(json.dumps(json.loads(out.content[0].text), indent=2))
            elif low == "/functions":
                out = await session.call_tool("list_functions", {})
                print(", ".join(json.loads(out.content[0].text)))
            else:
                res = await answer(q, llm=llm, executor=McpExecutor(session, dry_run=dry), strategy=strategy,
                                   max_retries=int(cfg["translator"]["max_retries"]), db=db, model=model,
                                   backend=backend_name, session=session_id)
                if res.status != "not_calculation":
                    show(res)
                elif looks_like_math(q):
                    print("calc> I could not turn that into a supported expression. Try rephrasing.")
                else:
                    history.append({"role": "user", "content": q})
                    reply = await llm.chat_text(history)
                    history.append({"role": "assistant", "content": reply})
                    print(f"llm> {reply}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="mcpcalc chat client")
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--url", help="connect to a running HTTP server, e.g. http://127.0.0.1:8765/mcp")
    parser.add_argument("--model")
    parser.add_argument("--strategy", choices=list(STRATEGIES))
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()