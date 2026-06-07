"""
Project Magpie — Streamlit Dashboard

실행: streamlit run dashboard/run.py
"""

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# `streamlit run dashboard/run.py`로 실행될 때 프로젝트 루트를 import path에 보장합니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.session import init_session_state  # noqa: E402
from dashboard.views.agent import render_agent_dashboard  # noqa: E402
from dashboard.views.bat_daemon import (  # noqa: E402
    render_bat_daemon_dashboard,
    render_wallet_dashboard,
)

load_dotenv()


def main() -> None:
    st.set_page_config(
        page_title="Magpie Dashboard",
        layout="wide",
    )

    init_session_state()

    st.title("Magpie Dashboard", text_alignment="center")
    st.caption(
        "LangGraph 에이전트 실행 흐름 · Bat Daemon tick 판정 · "
        "MongoDB 저장/조회 상태를 시각화합니다.",
        text_alignment="center",
    )

    agent_tab, daemon_tab, wallet_tab = st.tabs(["Magpie Agent", "Bat Daemon", "Wallet"])
    with agent_tab:
        render_agent_dashboard()
    with daemon_tab:
        render_bat_daemon_dashboard()
    with wallet_tab:
        render_wallet_dashboard()


if __name__ == "__main__":
    main()
