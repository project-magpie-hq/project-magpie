from typing import Any

import streamlit as st


def init_session_state() -> None:
    if "app" not in st.session_state:
        from magpie_agent.graph import build_graph

        with st.spinner("🔧 LangGraph 그래프를 초기화하는 중..."):
            st.session_state.app = build_graph()

    defaults: dict[str, Any] = {
        "history": [],
        "user_id": "test_developer_001",
        "thread_id": "dashboard_session_001",
        "bat_target_snapshot": None,
        "bat_live_result": None,
        "bat_backtest_result": None,
    }
    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val
