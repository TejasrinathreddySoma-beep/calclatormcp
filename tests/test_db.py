from mcpcalc.db import Database


def test_log_and_stats(db):
    for i, status in enumerate(["ok", "ok", "ok", "error"]):
        db.log_request(session="s", user_text=f"q{i}", status=status, total_ms=100.0 * (i + 1), llm_ms=50.0,
                       exec_ms=1.0, retries=i % 2)
    db.log_audit("mcp", "evaluate", "1+1", "allowed")
    db.log_audit("mcp", "evaluate", "__import__('os')", "blocked", "forbidden syntax")
    stats = db.stats()
    assert stats["total_requests"] == 4 and stats["ok"] == 3 and stats["success_rate"] == 0.75
    assert stats["blocked_by_policy"] == 1
    assert stats["p50_ms"] in (200.0, 300.0) and stats["p95_ms"] == 400.0
    assert stats["avg_retries"] == 0.5
    assert [r["user_text"] for r in db.recent_requests(2)] == ["q3", "q2"]
    assert db.recent_audit()[0]["decision"] == "blocked"


def test_empty_stats(db):
    assert db.stats()["total_requests"] == 0 and db.stats()["success_rate"] == 0.0


def test_persists_across_instances(tmp_path):
    path = tmp_path / "nested" / "x.db"
    Database(path).log_request(user_text="hello", status="ok")
    assert Database(path).recent_requests()[0]["user_text"] == "hello"
