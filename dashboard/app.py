"""Streamlit dashboard: live request log, safety audit and benchmark results.

    pip install -e ".[dashboard]"
    streamlit run dashboard/app.py
"""
import os
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="mcpcalc dashboard", layout="wide")
st.title("mcpcalc - verified tool use for local LLMs")

db_path = st.sidebar.text_input("SQLite database", os.environ.get("MCPCALC_DB", "data/mcpcalc.db"))
results_dir = st.sidebar.text_input("Benchmark results folder", os.environ.get("MCPCALC_RESULTS", "benchmarks/results"))
if st.sidebar.button("Refresh"):
    st.rerun()


def query(sql: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(sql, conn)


def load_table(sql: str) -> pd.DataFrame | None:
    if not Path(db_path).exists():
        return None
    try:
        return query(sql)
    except Exception as ex:  # noqa: BLE001 - show the problem instead of crashing the page
        st.error(f"Could not read {db_path}: {ex}")
        return None


overview, requests_tab, audit_tab, bench_tab = st.tabs(["Overview", "Requests", "Safety audit", "Benchmark"])

with overview:
    df = load_table("SELECT * FROM requests ORDER BY id")
    if df is None or df.empty:
        st.info("No requests logged yet. Run `mcpcalc-chat` and ask a few questions.")
    else:
        ok = (df["status"] == "ok").sum()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Requests", len(df))
        c2.metric("Success rate", f"{100 * ok / len(df):.1f}%")
        c3.metric("p50 latency", f"{df['total_ms'].quantile(0.5):.0f} ms")
        c4.metric("p95 latency", f"{df['total_ms'].quantile(0.95):.0f} ms")
        c5.metric("Avg retries", f"{df['retries'].fillna(0).mean():.2f}")
        left, right = st.columns(2)
        left.subheader("Outcome per request")
        left.bar_chart(df["status"].value_counts())
        right.subheader("Latency over time (ms)")
        right.line_chart(df.set_index(pd.to_datetime(df["ts"], unit="s"))[["llm_ms", "exec_ms", "total_ms"]])
        st.subheader("Most used functions")
        names = df["expression"].dropna().apply(lambda e: re.findall(r"[a-z_0-9]+(?=\()", e.lower())).explode().dropna()
        if not names.empty:
            st.bar_chart(names.value_counts().head(15))
        st.subheader("Success by model and strategy")
        grouped = df.groupby(["model", "strategy"]).agg(
            requests=("id", "count"), success=("status", lambda s: (s == "ok").mean()),
            avg_total_ms=("total_ms", "mean"), avg_retries=("retries", "mean")).reset_index()
        st.dataframe(grouped, use_container_width=True)

with requests_tab:
    df = load_table("SELECT * FROM requests ORDER BY id DESC LIMIT 500")
    if df is not None and not df.empty:
        wanted = st.multiselect("Status", sorted(df["status"].dropna().unique()), default=None)
        view = df[df["status"].isin(wanted)] if wanted else df
        view = view.assign(time=pd.to_datetime(view["ts"], unit="s")).drop(columns=["ts"])
        st.dataframe(view, use_container_width=True)
    else:
        st.info("Nothing to show yet.")

with audit_tab:
    df = load_table("SELECT * FROM audit ORDER BY id DESC LIMIT 500")
    if df is not None and not df.empty:
        st.bar_chart(df["decision"].value_counts())
        st.caption("Every expression the server received, with the policy decision (allowed / blocked / dry_run).")
        st.dataframe(df.assign(time=pd.to_datetime(df["ts"], unit="s")).drop(columns=["ts"]),
                     use_container_width=True)
    else:
        st.info("No audit entries yet.")

with bench_tab:
    runs = sorted((p for p in Path(results_dir).glob("*/results.csv")), reverse=True)
    if not runs:
        st.info("No benchmark runs found. Run `mcpcalc-bench --models llama3.1:8b qwen2.5:7b`.")
    else:
        chosen = st.selectbox("Run", runs, format_func=lambda p: p.parent.name)
        res = pd.read_csv(chosen)
        st.caption(f"{len(res)} runs - models: {', '.join(sorted(res['model'].unique()))}")
        acc = res.groupby(["strategy", "model"])["correct"].mean().unstack("model") * 100
        st.subheader("End-to-end accuracy (%) by strategy")
        st.bar_chart(acc)
        st.subheader("Accuracy (%) by difficulty")
        st.dataframe((res.groupby(["model", "strategy", "difficulty"])["correct"].mean().unstack("difficulty") * 100)
                     .round(1), use_container_width=True)
        st.subheader("Where the failures come from")
        st.bar_chart(res.groupby(["strategy", "outcome"]).size().unstack("outcome").fillna(0))
        st.subheader("Hardest questions (lowest accuracy across models and strategies)")
        hardest = (res.groupby(["id", "question", "reference"])["correct"].mean().reset_index()
                   .sort_values("correct").head(15))
        st.dataframe(hardest, use_container_width=True)
        st.subheader("Wrong expressions written by the models")
        st.dataframe(res[res["outcome"] != "correct"][["model", "strategy", "question", "reference", "expression",
                                                       "outcome", "error"]].head(200), use_container_width=True)
