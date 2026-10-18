from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")
from streamlit.testing.v1 import AppTest  # noqa: E402

from mcpcalc import benchmark  # noqa: E402
from mcpcalc.db import Database  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
QUESTIONS = Path(__file__).resolve().parents[1] / "benchmarks" / "questions.jsonl"


def test_dashboard_renders_with_data(tmp_path, monkeypatch):
    db = Database(tmp_path / "d.db")
    for i, status in enumerate(["ok", "ok", "blocked", "error"]):
        db.log_request(user_text=f"q{i}", expression="sqrt(4)+sin(30)", status=status, model="m", strategy="full",
                       total_ms=10.0 * (i + 1), llm_ms=8.0, exec_ms=1.0, retries=i % 2)
    db.log_audit("mcp", "evaluate", "1+1", "allowed")
    benchmark.main(["--llm", "oracle", "--questions", str(QUESTIONS), "--limit", "16", "--strategies", "full",
                    "baseline", "--out", str(tmp_path / "res")])
    monkeypatch.setenv("MCPCALC_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("MCPCALC_RESULTS", str(tmp_path / "res"))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 4
    assert any(m.label == "Requests" and m.value == "4" for m in at.metric)


def test_dashboard_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MCPCALC_DB", str(tmp_path / "none.db"))
    monkeypatch.setenv("MCPCALC_RESULTS", str(tmp_path / "none"))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception and len(at.info) >= 1
