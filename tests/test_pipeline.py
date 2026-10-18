import json

from conftest import run

from mcpcalc.executors import LocalExecutor
from mcpcalc.llm import ScriptedLLM
from mcpcalc.pipeline import answer
from mcpcalc.safety import Policy


def reply(expression, calc=True):
    return json.dumps({"is_calculation": calc, "expression": expression})


def test_executor_ok_and_audit(executor, db):
    res = run(executor.evaluate("sqrt(144)+5^2"))
    assert res.status == "ok" and res.value == 37 and res.functions == ["sqrt"] and res.exec_ms >= 0
    assert db.recent_audit()[0]["decision"] == "allowed"


def test_executor_blocks_and_audits(executor, db):
    res = run(executor.evaluate("__import__('os').system('echo hi')"))
    assert res.status == "blocked" and res.value is None
    row = db.recent_audit()[0]
    assert row["decision"] == "blocked" and row["reason"] and row["expression"].startswith("__import__")


def test_executor_reports_math_errors(executor):
    res = run(executor.evaluate("1/0"))
    assert res.status == "error" and "division" in res.error


def test_dry_run_validates_but_never_executes(backend, db):
    executor = LocalExecutor(backend, Policy(dry_run=True), db)
    res = run(executor.evaluate("sin(30)"))
    assert res.status == "dry_run" and res.value is None and res.functions == ["sin"]
    assert db.recent_audit()[0]["decision"] == "dry_run"
    per_call = LocalExecutor(backend, Policy(), db)
    assert run(per_call.evaluate("1+1", dry_run=True)).status == "dry_run"
    assert run(per_call.evaluate("1+1")).value == 2


def test_backend_crash_is_contained(db):
    class Broken:
        name, blocking_ui = "broken", False

        def evaluate(self, expression):
            raise RuntimeError("boom")

    res = run(LocalExecutor(Broken(), Policy(), db).evaluate("1+1"))
    assert res.status == "error" and "boom" in res.error


def test_pipeline_end_to_end_logs_the_request(executor, db):
    res = run(answer("10 pencils at 5 each", llm=ScriptedLLM([reply("10*5")]), executor=executor,
                     strategy="full", db=db, model="fake", backend="python", session="t"))
    assert res.status == "ok" and res.value == 50 and res.expression == "10*5"
    row = db.recent_requests(1)[0]
    assert row["status"] == "ok" and row["result"] == 50 and row["model"] == "fake" and row["strategy"] == "full"
    assert row["total_ms"] >= row["exec_ms"] >= 0


def test_pipeline_not_a_calculation(executor):
    res = run(answer("hello", llm=ScriptedLLM([reply("", calc=False)]), executor=executor))
    assert res.status == "not_calculation"


def test_unsupported_function_is_blocked_without_retry(executor):
    llm = ScriptedLLM([reply("10*sin(deg(60))")])
    res = run(answer("ladder", llm=llm, executor=executor, strategy="prompt"))
    assert res.status == "blocked" and "deg" in res.error


def test_retry_strategy_recovers(executor):
    llm = ScriptedLLM([reply("10*sin(deg(60))"), reply("10*sin(60)")])
    res = run(answer("ladder", llm=llm, executor=executor, strategy="full"))
    assert res.status == "ok" and res.value == __import__("pytest").approx(8.6602540378) and res.retries == 1


def test_math_error_is_reported(executor):
    res = run(answer("x", llm=ScriptedLLM([reply("5/0")]), executor=executor))
    assert res.status == "error"
