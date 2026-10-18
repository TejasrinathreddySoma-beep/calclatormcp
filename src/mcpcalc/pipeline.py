"""One question -> translate -> execute -> log. Shared by the chat client and the benchmark."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .translator import translate


@dataclass
class Result:
    question: str
    status: str  # ok | not_calculation | blocked | error | dry_run
    expression: str = ""
    normalized: str = ""
    value: float | None = None
    error: str = ""
    retries: int = 0
    llm_ms: float = 0.0
    exec_ms: float = 0.0
    total_ms: float = 0.0


async def answer(question: str, *, llm, executor, strategy: str = "full", max_retries: int = 2, db=None,
                 model: str = "", backend: str = "", session: str = "") -> Result:
    started = time.perf_counter()
    tr = await translate(llm, question, strategy, max_retries)
    if not tr.is_calculation:
        result = Result(question, "not_calculation", tr.expression, tr.normalized, error=tr.error,
                        retries=tr.retries, llm_ms=tr.llm_ms)
    else:
        ex = await executor.evaluate(tr.expression)
        result = Result(question, ex.status, tr.expression, tr.normalized, ex.value, ex.error, tr.retries,
                        tr.llm_ms, ex.exec_ms)
    result.total_ms = (time.perf_counter() - started) * 1000
    if db is not None:
        db.log_request(session=session, user_text=question, normalized_text=result.normalized, model=model,
                       strategy=strategy, backend=backend, expression=result.expression, result=result.value,
                       status=result.status, error=result.error, retries=result.retries, llm_ms=result.llm_ms,
                       exec_ms=result.exec_ms, total_ms=result.total_ms)
    return result
