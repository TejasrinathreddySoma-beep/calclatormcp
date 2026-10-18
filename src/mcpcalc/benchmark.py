"""Benchmark harness: models x strategies over the question set, with accuracy, error taxonomy and latency.

    mcpcalc-bench --models llama3.1:8b qwen2.5:7b                 # needs a running Ollama
    mcpcalc-bench --llm oracle --limit 40                          # sanity check of the harness (no LLM needed)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from .backends import get_backend
from .config import load_config
from .db import Database
from .executors import LocalExecutor
from .llm import OllamaLLM, OracleLLM
from .pipeline import answer
from .safety import Policy
from .translator import STRATEGIES

OUTCOMES = ["correct", "wrong_answer", "not_calculation", "blocked", "exec_error"]
FIELDS = ["model", "strategy", "id", "difficulty", "category", "question", "reference", "expression", "expected",
          "value", "correct", "outcome", "status", "retries", "llm_ms", "exec_ms", "error", "backend"]


def load_questions(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def is_correct(value, expected, rel: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return value is not None and math.isclose(value, expected, rel_tol=rel, abs_tol=abs_tol)


def classify(status: str, correct: bool) -> str:
    if status == "ok":
        return "correct" if correct else "wrong_answer"
    return {"not_calculation": "not_calculation", "blocked": "blocked"}.get(status, "exec_error")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


async def run_benchmark(questions, models, strategies, *, make_llm, executor, max_retries=2, concurrency=1,
                        db=None, backend_name="python", progress=None) -> list[dict]:
    rows: list[dict] = []
    gate = asyncio.Semaphore(concurrency)
    total = len(models) * len(strategies) * len(questions)

    async def one(model, strategy, llm, q):
        async with gate:
            if isinstance(llm, OracleLLM):
                llm.expression = q["reference_expression"]
            res = await answer(q["question"], llm=llm, executor=executor, strategy=strategy,
                               max_retries=max_retries, db=db, model=model, backend=backend_name,
                               session="benchmark")
        ok = res.status == "ok" and is_correct(res.value, q["expected"])
        rows.append({"model": model, "strategy": strategy, "id": q["id"], "difficulty": q["difficulty"],
                     "category": q["category"], "question": q["question"], "reference": q["reference_expression"],
                     "expression": res.expression, "expected": q["expected"], "value": res.value, "correct": ok,
                     "outcome": classify(res.status, ok), "status": res.status, "retries": res.retries,
                     "llm_ms": round(res.llm_ms, 1), "exec_ms": round(res.exec_ms, 2), "error": res.error,
                     "backend": backend_name})
        if progress and len(rows) % 20 == 0:
            progress(len(rows), total)

    for model in models:
        llm = make_llm(model)
        warm_up = getattr(llm, "warm_up", None)
        if warm_up:  # load the model first, so the cold start is not counted in the latency figures
            await warm_up()
        for strategy in strategies:
            await asyncio.gather(*(one(model, strategy, llm, q) for q in questions))
    return rows


def summarize(rows: list[dict]) -> dict:
    groups: dict = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["strategy"])].append(r)
    summary = []
    for (model, strategy), items in sorted(groups.items()):
        n = len(items)
        k = sum(1 for r in items if r["correct"])
        low, high = wilson(k, n)
        entry = {"model": model, "strategy": strategy, "n": n, "accuracy": k / n, "ci_low": low, "ci_high": high,
                 "mean_retries": sum(r["retries"] for r in items) / n,
                 "mean_llm_ms": sum(r["llm_ms"] for r in items) / n,
                 "outcomes": {o: sum(1 for r in items if r["outcome"] == o) / n for o in OUTCOMES},
                 "by_difficulty": {}}
        for diff in ("easy", "medium", "hard", "advanced"):
            sub = [r for r in items if r["difficulty"] == diff]
            if sub:
                entry["by_difficulty"][diff] = sum(1 for r in sub if r["correct"]) / len(sub)
        summary.append(entry)
    return {"groups": summary}


def to_markdown(summary: dict) -> str:
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    lines = ["# Benchmark results", "", "## Accuracy (95% Wilson interval) and error taxonomy", "",
             "| model | strategy | n | accuracy | 95% CI | wrong answer | not calc | blocked | exec error "
             "| retries | LLM ms |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in summary["groups"]:
        o = g["outcomes"]
        lines.append(
            f"| {g['model']} | {g['strategy']} | {g['n']} | {pct(g['accuracy'])} | "
            f"{pct(g['ci_low'])}-{pct(g['ci_high'])} | {pct(o['wrong_answer'])} | "
            f"{pct(o['not_calculation'])} | {pct(o['blocked'])} | {pct(o['exec_error'])} | "
            f"{g['mean_retries']:.2f} | {g['mean_llm_ms']:.0f} |")
    lines += ["", "## Accuracy by difficulty", "", "| model | strategy | easy | medium | hard | advanced |",
              "|---|---|---|---|---|---|"]
    for g in summary["groups"]:
        d = g["by_difficulty"]
        lines.append(f"| {g['model']} | {g['strategy']} | " + " | ".join(pct(d[x]) if x in d else "-"
                                                                         for x in ("easy", "medium", "hard", "advanced")) + " |")
    return "\n".join(lines) + "\n"


def write_plots(summary: dict, out: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    written = []
    models = sorted({g["model"] for g in summary["groups"]})
    strategies = [s for s in STRATEGIES if any(g["strategy"] == s for g in summary["groups"])]
    width = 0.8 / max(1, len(models))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for i, model in enumerate(models):
        acc = [next((100 * g["accuracy"] for g in summary["groups"] if g["model"] == model and g["strategy"] == s), 0)
               for s in strategies]
        ax.bar([x + i * width for x in range(len(strategies))], acc, width, label=model)
    ax.set_xticks([x + width * (len(models) - 1) / 2 for x in range(len(strategies))])
    ax.set_xticklabels(strategies)
    ax.set_ylabel("end-to-end accuracy (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Accuracy by strategy")
    ax.legend()
    fig.tight_layout()
    path = out / "accuracy_by_strategy.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path.name)
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="mcpcalc benchmark")
    parser.add_argument("--config")
    parser.add_argument("--questions", default="benchmarks/questions.jsonl")
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--strategies", nargs="+", choices=list(STRATEGIES), default=list(STRATEGIES))
    parser.add_argument("--llm", choices=["ollama", "oracle"], default="ollama")
    parser.add_argument("--limit", type=int, help="random sample of N questions (seeded)")
    parser.add_argument("--difficulty", nargs="+", choices=["easy", "medium", "hard", "advanced"])
    parser.add_argument("--backend", choices=["python", "windows_calculator"], default="python",
                        help="who executes the expressions (windows_calculator is slow: use with --limit)")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-retries", type=int)
    parser.add_argument("--out", default="benchmarks/results")
    parser.add_argument("--db", help="also log every request to this SQLite database")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    questions = load_questions(args.questions)
    if args.difficulty:
        questions = [q for q in questions if q["difficulty"] in args.difficulty]
    if args.limit and args.limit < len(questions):
        questions = random.Random(7).sample(questions, args.limit)
    models = args.models or [cfg["llm"]["model"]]
    if args.llm == "oracle":
        models, args.concurrency = ["oracle"], 1
        make_llm = lambda _m: OracleLLM()  # noqa: E731
    else:
        make_llm = lambda m: OllamaLLM(m, cfg["llm"].get("host"), 0.0)  # noqa: E731

    backend = get_backend({"backend": args.backend, "angle_mode": cfg.get("angle_mode", "deg")})
    if getattr(backend, "blocking_ui", False):
        args.concurrency = 1  # one Calculator, one calculation at a time
    executor = LocalExecutor(backend, Policy(), None, source="benchmark")
    retries = cfg["translator"]["max_retries"] if args.max_retries is None else args.max_retries
    db = Database(args.db) if args.db else None
    started = time.time()
    rows = asyncio.run(run_benchmark(
        questions, models, args.strategies, make_llm=make_llm, executor=executor, max_retries=retries,
        concurrency=args.concurrency, db=db, backend_name=backend.name,
        progress=lambda done, total: print(f"  {done}/{total}", file=sys.stderr)))

    out = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(to_markdown(summary), encoding="utf-8")
    plots = write_plots(summary, out)
    print(to_markdown(summary))
    print(f"{len(rows)} runs in {time.time() - started:.1f}s -> {out} {plots}")


if __name__ == "__main__":
    main()