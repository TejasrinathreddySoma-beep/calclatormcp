import json

import pytest
from conftest import run

from mcpcalc.llm import ScriptedLLM
from mcpcalc.translator import check_expression, looks_like_math, normalize, translate


def reply(expression, calc=True):
    return json.dumps({"is_calculation": calc, "expression": expression})


@pytest.mark.parametrize("text,expected", [
    ("square root of 144 plus 5 squared", "sqrt(144) plus (5^2)"),
    ("square root of 144 plus 5 square", "sqrt(144) plus (5^2)"),
    ("7 cubed minus 3", "(7^3) minus 3"),
    ("5 factorial divided by 3 factorial", "factorial(5) divided by factorial(3)"),
    ("cube root of 27 times 4", "cbrt(27) times 4"),
    ("square root of 81", "sqrt(81)"),
    ("3.5 squared", "(3.5^2)"),
    ("i have 10 pencils", "i have 10 pencils"),
])
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_check_expression():
    assert check_expression("10*sin(60)") is None
    assert "deg" in check_expression("10*sin(deg(60))")
    assert "syntax" in check_expression("2+")
    assert check_expression("LOG(5,4)") is None


def test_looks_like_math():
    assert looks_like_math("what is 5 plus 3") and looks_like_math("sin 90")
    assert not looks_like_math("hello there, how are you")


def test_full_strategy_retries_after_invented_function():
    llm = ScriptedLLM([reply("10*sin(deg(60))"), reply("10*sin(60)")])
    tr = run(translate(llm, "ladder 10 m at 60 degrees", "full", max_retries=2))
    assert tr.expression == "10*sin(60)" and tr.retries == 1 and tr.is_calculation
    feedback = llm.calls[1][-1]["content"]
    assert "deg" in feedback and "unsupported" in feedback


@pytest.mark.parametrize("strategy", ["baseline", "prompt", "rewrite"])
def test_non_retry_strategies_return_the_first_answer(strategy):
    llm = ScriptedLLM([reply("10*sin(deg(60))"), reply("10*sin(60)")])
    tr = run(translate(llm, "x", strategy))
    assert tr.expression == "10*sin(deg(60))" and tr.retries == 0 and len(llm.calls) == 1


def test_retry_budget_is_respected():
    llm = ScriptedLLM([reply("nope(1)")])
    tr = run(translate(llm, "x", "full", max_retries=2))
    assert tr.retries == 2 and len(llm.calls) == 3 and tr.expression == "nope(1)"


def test_rewrite_is_applied_only_by_rewrite_strategies():
    sent = {}
    for strategy in ("prompt", "rewrite"):
        llm = ScriptedLLM([reply("(5^2)")])
        run(translate(llm, "5 squared", strategy))
        sent[strategy] = llm.calls[0][1]["content"]
    assert sent["prompt"] == "5 squared" and sent["rewrite"] == "(5^2)"


def test_prompts_differ_between_baseline_and_full():
    a, b = ScriptedLLM([reply("1")]), ScriptedLLM([reply("1")])
    run(translate(a, "x", "baseline"))
    run(translate(b, "x", "prompt"))
    assert len(a.calls[0][0]["content"]) < len(b.calls[0][0]["content"])


def test_invalid_json_is_handled():
    tr = run(translate(ScriptedLLM(["not json"]), "x", "prompt"))
    assert not tr.is_calculation and "invalid JSON" in tr.error
    llm = ScriptedLLM(["not json", reply("1+1")])
    tr = run(translate(llm, "x", "full"))
    assert tr.is_calculation and tr.expression == "1+1" and tr.retries == 1


def test_chat_message_is_not_a_calculation():
    tr = run(translate(ScriptedLLM([reply("", calc=False)]), "hello", "full"))
    assert not tr.is_calculation


def test_unknown_strategy():
    with pytest.raises(ValueError):
        run(translate(ScriptedLLM([reply("1")]), "x", "magic"))
