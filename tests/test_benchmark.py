import json
from pathlib import Path

import pytest
from conftest import run

from mcpcalc.backends import PythonBackend
from mcpcalc.benchmark import classify, is_correct, load_questions, run_benchmark, summarize, to_markdown, wilson
from mcpcalc.executors import LocalExecutor
from mcpcalc.llm import OracleLLM, ScriptedLLM
from mcpcalc.questions import QUOTAS, generate
from mcpcalc.safety import Policy

QUESTIONS = Path(__file__).resolve().parents[1] / "benchmarks" / "questions.jsonl"


def test_generation_is_reproducible_and_balanced():
    a, b = generate(42), generate(42)
    assert a == b and generate(1) != a
    assert len(a) == sum(QUOTAS.values()) == 280
    assert len({r["question"] for r in a}) == len(a)
    for difficulty, quota in QUOTAS.items():
        assert sum(1 for r in a if r["difficulty"] == difficulty) == quota


def test_committed_question_file_matches_the_generator():
    assert load_questions(QUESTIONS) == generate(42)


def test_reference_expressions_give_the_expected_values():
    backend = PythonBackend()
    for q in load_questions(QUESTIONS):
        assert backend.evaluate(q["reference_expression"]) == pytest.approx(q["expected"]), q["id"]
        assert q["difficulty"] in QUOTAS and q["question"].strip()


def test_helpers():
    assert is_correct(50.0, 50) and is_correct(1 / 3, 0.3333333) and not is_correct(None, 1)
    assert not is_correct(51, 50)
    assert classify("ok", True) == "correct" and classify("ok", False) == "wrong_answer"
    assert classify("blocked", False) == "blocked" and classify("error", False) == "exec_error"
    assert classify("not_calculation", False) == "not_calculation"
    low, high = wilson(50, 100)
    assert 0.40 < low < 0.5 < high < 0.60
    assert wilson(0, 0) == (0.0, 0.0)


def bench(make_llm, strategies, questions, models=("m",)):
    executor = LocalExecutor(PythonBackend(), Policy())
    return run(run_benchmark(questions, list(models), strategies, make_llm=make_llm, executor=executor))


def test_oracle_gets_a_perfect_score_on_every_question():
    questions = load_questions(QUESTIONS)
    rows = bench(lambda m: OracleLLM(), ["full"], questions)
    assert len(rows) == 280 and all(r["correct"] for r in rows)


def test_wrong_and_unsupported_answers_are_classified():
    questions = [{"id": "q1", "difficulty": "easy", "category": "x", "question": "ten times five",
                  "reference_expression": "10*5", "expected": 50.0}]
    wrong = bench(lambda m: ScriptedLLM([json.dumps({"is_calculation": True, "expression": "10+5"})]), ["prompt"],
                  questions)
    assert wrong[0]["outcome"] == "wrong_answer" and not wrong[0]["correct"]
    blocked = bench(lambda m: ScriptedLLM([json.dumps({"is_calculation": True, "expression": "deg(5)*10"})]),
                    ["prompt"], questions)
    assert blocked[0]["outcome"] == "blocked"
    no_calc = json.dumps({"is_calculation": False, "expression": ""})
    chat = bench(lambda m: ScriptedLLM([no_calc]), ["prompt"], questions)
    assert chat[0]["outcome"] == "not_calculation"


def test_retry_strategy_beats_plain_prompt_on_a_flaky_model():
    questions = [{"id": "q1", "difficulty": "advanced", "category": "x", "question": "ladder",
                  "reference_expression": "10*sin(60)", "expected": 8.660254037844386}]
    bad, good = json.dumps({"is_calculation": True, "expression": "10*sin(deg(60))"}), json.dumps(
        {"is_calculation": True, "expression": "10*sin(60)"})
    by = {s: bench(lambda m: ScriptedLLM([bad, good]), [s], questions)[0] for s in ("prompt", "full")}
    assert not by["prompt"]["correct"] and by["prompt"]["outcome"] == "blocked"
    assert by["full"]["correct"] and by["full"]["retries"] == 1


def test_summary_and_markdown():
    rows = bench(lambda m: OracleLLM(), ["baseline", "full"], load_questions(QUESTIONS)[:40])
    summary = summarize(rows)
    assert [g["strategy"] for g in summary["groups"]] == ["baseline", "full"]
    assert all(g["accuracy"] == 1.0 and g["n"] == 40 for g in summary["groups"])
    md = to_markdown(summary)
    assert "| model | strategy |" in md and "100.0%" in md


def test_each_model_is_warmed_up_once_before_timing():
    calls = []

    class Warm(OracleLLM):
        def __init__(self, name):
            super().__init__()
            self.name = name

        async def warm_up(self):
            calls.append(self.name)

    questions = load_questions(QUESTIONS)[:6]
    executor = LocalExecutor(PythonBackend(), Policy())
    run(run_benchmark(questions, ["a", "b"], ["baseline", "full"], make_llm=Warm, executor=executor))
    assert calls == ["a", "b"]