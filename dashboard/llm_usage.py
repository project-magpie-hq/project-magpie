from typing import Any

import pandas as pd
import streamlit as st

from dashboard.asyncio_utils import run_async_task
from magpie_agent.llm import fetch_recent_llm_usage_runs


def format_llm_cost(value: Any) -> str:
    try:
        return f"${float(value):,.6f}"
    except (TypeError, ValueError):
        return "$0.000000"


def render_llm_usage_metrics(usage: dict[str, Any] | None, title: str = "LLM 사용량 / 예상 비용") -> None:
    st.markdown(f"#### {title}")
    if not usage:
        st.caption("LLM 사용량 정보가 없습니다.")
        return

    cols = st.columns(5)
    cols[0].metric("LLM Calls", f"{usage.get('total_calls', 0):,}")
    cols[1].metric("Input Tokens", f"{usage.get('input_tokens', 0):,}")
    cols[2].metric("Output Tokens", f"{usage.get('output_tokens', 0):,}")
    cols[3].metric("Total Tokens", f"{usage.get('total_tokens', 0):,}")
    cols[4].metric("Est. Cost", format_llm_cost(usage.get("estimated_cost_usd", 0.0)))

    with st.expander("LLM 사용량 상세", expanded=False):
        _render_usage_breakdown("Agent별", "agent", usage.get("by_agent") or {})
        _render_usage_breakdown("Model별", "model", usage.get("by_model") or {})
        st.caption(str(usage.get("pricing_note") or "비용은 설정된 단가 기반의 추정치입니다."))


def render_recent_llm_usage_runs(user_id: str | None, run_type: str | list[str] | None = None, limit: int = 20) -> None:
    try:
        rows = run_async_task(fetch_recent_llm_usage_runs(user_id=user_id, run_type=run_type, limit=limit))
    except Exception as exc:
        st.warning(f"LLM 사용량 기록을 불러오지 못했습니다: {exc}")
        return

    if not rows:
        st.caption("아직 저장된 LLM 사용량 기록이 없습니다.")
        return

    table_rows = []
    for row in rows:
        usage = row.get("usage") or {}
        table_rows.append(
            {
                "created_at": row.get("created_at"),
                "run_type": row.get("run_type"),
                "graph": row.get("graph_name"),
                "status": row.get("status"),
                "calls": usage.get("total_calls", 0),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "estimated_cost_usd": usage.get("estimated_cost_usd", 0.0),
                "thread_id": row.get("thread_id"),
            }
        )
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)


def _render_usage_breakdown(title: str, key_name: str, rows: dict[str, dict[str, Any]]) -> None:
    if not rows:
        return

    st.markdown(f"###### {title}")
    st.dataframe(
        pd.DataFrame([{key_name: key, **value} for key, value in sorted(rows.items())]),
        width="stretch",
        hide_index=True,
    )
