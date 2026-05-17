"""
Project Magpie — Streamlit Dashboard

실행: streamlit run dashboard/run.py
"""

import streamlit as st
from dotenv import load_dotenv

from dashboard.session import init_session_state
from dashboard.sidebar import render_sidebar
from dashboard.views.agent import render_agent_dashboard
from dashboard.views.bat_daemon import render_bat_daemon_dashboard

load_dotenv()


def main() -> None:
    st.set_page_config(
        page_title="Magpie Dashboard",
        layout="wide",
    )

    init_session_state()
    render_sidebar()

    st.title("Magpie Dashboard", text_alignment="center")
    st.caption(
        "LangGraph 에이전트 실행 흐름 · Bat Daemon tick 판정 · "
        "MongoDB 저장/조회 상태를 시각화합니다.",
        text_alignment="center",
    )

    agent_tab, daemon_tab = st.tabs(["Magpie Agent", "Bat Daemon"])
    with agent_tab:
        render_agent_dashboard()
    with daemon_tab:
        render_bat_daemon_dashboard()


if __name__ == "__main__":
    main()
