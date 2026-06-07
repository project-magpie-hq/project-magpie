"""
Project Magpie — Streamlit Backtest Dashboard

실행: streamlit run dashboard/backtest.py
"""

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# `streamlit run dashboard/backtest.py`로 실행될 때 프로젝트 루트를 import path에 보장합니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.session import init_session_state  # noqa: E402
from dashboard.views.bat_daemon import render_backtest_dashboard  # noqa: E402

load_dotenv()


def main() -> None:
    st.set_page_config(
        page_title="Magpie Backtest Dashboard",
        layout="wide",
    )

    init_session_state()

    st.title("Magpie Backtest Dashboard", text_alignment="center")
    st.caption(
        "원본 전략을 backtest_id로 복제해 과거 tick 기반으로 run.py와 동일한 체결 흐름을 재생합니다.",
        text_alignment="center",
    )

    render_backtest_dashboard()


if __name__ == "__main__":
    main()
