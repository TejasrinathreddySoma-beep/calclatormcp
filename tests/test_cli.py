import json
from pathlib import Path

import pytest

from mcpcalc import benchmark, client, questions
from mcpcalc.backends import PythonBackend
from mcpcalc.config import load_config
from mcpcalc.pipeline import Result

QUESTIONS = Path(__file__).resolve().parents[1] / "benchmarks" / "questions.jsonl"


def test_config_merges_yaml_over_defaults(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("llm:\n  model: llama3.1:8b\nsafety:\n  dry_run: true\nbackend: python\n")
    cfg = load_config(path)
    assert cfg["llm"]["model"] == "llama3.1:8b" and cfg["llm"]["host"].startswith("http")  # nested merge
    assert cfg["safety"]["dry_run"] is True and cfg["safety"]["max_nodes"] == 120
    assert load_config(tmp_path / "nope.yaml")["llm"]["model"] == "qwen2.5:7b"


def test_config_path_from_environment(tmp_path, monkeypatch):
    path = tmp_path / "env.yaml"
    path.write_text("angle_mode: rad\n")
    monkeypatch.setenv("MCPCALC_CONFIG", str(path))
    assert load_config()["angle_mode"] == "rad"


def test_questions_cli_writes_the_dataset(tmp_path):
    out = tmp_path / "q.jsonl"
    questions.main(["--out", str(out), "--seed", "42"])
    assert [json.loads(line) for line in out.read_text().splitlines()] == questions.generate(42)


def test_benchmark_cli_writes_csv_summary_and_json(tmp_path, capsys):
    benchmark.main(["--llm", "oracle", "--questions", str(QUESTIONS), "--limit", "24", "--strategies", "full",
                    "baseline", "--out", str(tmp_path), "--db", str(tmp_path / "bench.db")])
    run_dir = next(tmp_path.glob("2*"))
    rows = (run_dir / "results.csv").read_text().splitlines()
    assert len(rows) == 1 + 2 * 24 and rows[0].startswith("model,strategy,id") and rows[0].endswith(",backend")
    assert rows[1].endswith(",python")
    assert "| oracle | full | 24 | 100.0%" in (run_dir / "summary.md").read_text()
    assert json.loads((run_dir / "summary.json").read_text())["groups"][0]["n"] == 24
    from mcpcalc.db import Database
    assert Database(tmp_path / "bench.db").stats()["total_requests"] == 48


def test_benchmark_difficulty_filter(tmp_path):
    benchmark.main(["--llm", "oracle", "--questions", str(QUESTIONS), "--difficulty", "easy", "--strategies",
                    "full", "--out", str(tmp_path)])
    rows = (next(tmp_path.glob("2*")) / "results.csv").read_text().splitlines()
    assert len(rows) == 1 + 60


def test_plot_is_written_when_matplotlib_is_available(tmp_path):
    pytest.importorskip("matplotlib")
    rows = benchmark.asyncio.run(benchmark.run_benchmark(
        benchmark.load_questions(QUESTIONS)[:10], ["m"], ["full", "baseline"],
        make_llm=lambda m: benchmark.OracleLLM(),
        executor=benchmark.LocalExecutor(PythonBackend(), benchmark.Policy())))
    assert benchmark.write_plots(benchmark.summarize(rows), tmp_path) == ["accuracy_by_strategy.png"]
    assert (tmp_path / "accuracy_by_strategy.png").stat().st_size > 1000


def test_client_output_formatting(capsys):
    assert client.fmt(50.0) == "50" and client.fmt(8.660254037844386) == "8.660254038"
    client.show(Result("q", "ok", "10*5", value=50.0))
    client.show(Result("q", "blocked", "deg(1)", error="function 'deg' is not allowed"))
    client.show(Result("q", "error", "1/0", error="division by zero"))
    client.show(Result("q", "dry_run", "sin(30)"))
    out = capsys.readouterr().out
    assert "calc> 50" in out and "blocked by the safety policy" in out
    assert "could not calculate: division by zero" in out and "dry run" in out


def test_windows_config_selects_the_windows_backend():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.windows.yaml")
    assert cfg["backend"] == "windows_calculator" and cfg["server"]["workers"] == 1
    assert cfg["server"]["timeout_s"] >= 60  # a Calculator run takes seconds