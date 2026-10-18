import asyncio
import json
import socket
import subprocess
import sys
import time

import pytest
import yaml
from conftest import run
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcpcalc.db import Database
from mcpcalc.executors import ExecResult, McpExecutor
from mcpcalc.server import build_server


def text_of(result):
    if isinstance(result, tuple):
        result = result[0]
    return result[0].text


async def call(mcp, tool, **args):
    return text_of(await mcp.call_tool(tool, args))


def test_server_registers_the_expected_tools(cfg):
    names = {t.name for t in run(build_server(cfg).list_tools())}
    assert names == {"evaluate", "set_angle_mode", "list_functions", "server_stats"}


def test_evaluate_ok_blocked_error_dry_run(cfg):
    async def go():
        mcp = build_server(cfg)
        ok = json.loads(await call(mcp, "evaluate", expression="sqrt(144)+5^2"))
        blocked = json.loads(await call(mcp, "evaluate", expression="__import__('os').getcwd()"))
        err = json.loads(await call(mcp, "evaluate", expression="1/0"))
        dry = json.loads(await call(mcp, "evaluate", expression="sin(30)", dry_run=True))
        return ok, blocked, err, dry

    ok, blocked, err, dry = run(go())
    assert ok["status"] == "ok" and ok["value"] == 37
    assert blocked["status"] == "blocked" and blocked["value"] is None
    assert err["status"] == "error" and "division" in err["error"]
    assert dry["status"] == "dry_run" and dry["functions"] == ["sin"]
    decisions = [r["decision"] for r in Database(cfg["database"]["path"]).recent_audit()]
    assert sorted(decisions) == ["allowed", "allowed", "blocked", "dry_run"]


def test_server_wide_dry_run_never_executes(cfg):
    cfg["safety"]["dry_run"] = True
    out = json.loads(run(call(build_server(cfg), "evaluate", expression="2+2")))
    assert out["status"] == "dry_run" and out["value"] is None


def test_allowlist_from_config(cfg):
    cfg["safety"]["allowed_functions"] = ["sqrt"]
    mcp = build_server(cfg)
    assert json.loads(run(call(mcp, "evaluate", expression="sqrt(9)")))["value"] == 3
    assert json.loads(run(call(mcp, "evaluate", expression="sin(9)")))["status"] == "blocked"
    assert json.loads(run(call(mcp, "list_functions"))) == ["sqrt"]


def test_angle_mode_tool(cfg):
    async def go():
        mcp = build_server(cfg)
        await call(mcp, "set_angle_mode", mode="rad")
        return json.loads(await call(mcp, "evaluate", expression="sin(pi/2)"))["value"], await call(
            mcp, "set_angle_mode", mode="bogus")

    value, message = run(go())
    assert value == pytest.approx(1) and message.startswith("Error")


def test_many_concurrent_requests_all_succeed_and_are_counted(cfg):
    async def go():
        mcp = build_server(cfg)
        outs = await asyncio.gather(*(call(mcp, "evaluate", expression=f"{i}*2") for i in range(60)))
        stats = json.loads(await call(mcp, "server_stats"))
        return [json.loads(o)["value"] for o in outs], stats

    values, stats = run(go())
    assert values == [i * 2 for i in range(60)] and stats["backend"] == "python" and stats["queue_depth"] == 0


def test_busy_server_reports_an_error_instead_of_hanging(cfg):
    cfg["server"].update(queue_size=1, workers=1)

    async def go():
        mcp = build_server(cfg)

        async def slow_handler(expression, dry_run=False):
            await asyncio.sleep(0.2)
            return ExecResult("ok", 1.0)

        mcp.state.queue._handler = slow_handler
        outs = await asyncio.gather(*(call(mcp, "evaluate", expression="1+1") for _ in range(6)))
        return [json.loads(o) for o in outs]

    results = run(go())
    assert any(r["status"] == "error" and "busy" in r["error"] for r in results)
    assert any(r["status"] == "ok" for r in results)


# ---------------------------------------------------------------- real processes
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_config(tmp_path, **server):
    cfg = {"database": {"path": str(tmp_path / "live.db")}, "server": server}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path, cfg["database"]["path"]


@pytest.mark.integration
def test_http_server_serves_several_clients_at_once(tmp_path):
    try:
        from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
    except ImportError:  # older mcp versions
        from mcp.client.streamable_http import streamablehttp_client

    port = free_port()
    config, db_path = write_config(tmp_path, transport="streamable-http", host="127.0.0.1", port=port)
    proc = subprocess.Popen([sys.executable, "-m", "mcpcalc.server", "--config", str(config)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                if proc.poll() is not None:
                    pytest.fail(f"server exited early: {proc.stderr.read().decode()[:500]}")
                time.sleep(0.2)
        else:
            pytest.fail("server did not start")

        async def one_client(i):
            async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp") as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    ex = McpExecutor(session)
                    good = await ex.evaluate(f"{i}+100")
                    bad = await ex.evaluate("__import__('os')")
                    return good.value, bad.status

        results = asyncio.run(_gather([one_client(i) for i in range(8)]))
        assert [r[0] for r in results] == [i + 100 for i in range(8)]
        assert all(r[1] == "blocked" for r in results)
        audit = Database(db_path).recent_audit(100)
        assert sum(1 for a in audit if a["decision"] == "allowed") == 8
        assert sum(1 for a in audit if a["decision"] == "blocked") == 8
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def _gather(coros):
    return await asyncio.gather(*coros)


@pytest.mark.integration
def test_stdio_server_round_trip(tmp_path):
    config, _ = write_config(tmp_path, transport="stdio")

    async def go():
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "mcpcalc.server", "--config", str(config)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await McpExecutor(session).evaluate("5*log(5,4)")
                dry = await McpExecutor(session, dry_run=True).evaluate("sin(30)")
                return res, dry

    res, dry = asyncio.run(go())
    assert res.status == "ok" and res.value == pytest.approx(5.804820237218405)
    assert dry.status == "dry_run"
