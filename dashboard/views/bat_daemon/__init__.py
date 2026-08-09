import streamlit as st

from dashboard.llm_usage import render_recent_llm_usage_runs

from .backtest import render_backtest_daemon_panel
from .live import render_bat_target_panel, render_daemon_controls, render_live_daemon_panel, render_wallet_control_panel


def render_bat_daemon_dashboard() -> None:
    st.subheader("Bat Daemon Monitor")
    st.caption("DB monitoring target과 실시간 tick 변화를 기준으로 run.py의 감시 흐름을 dry-run으로 관찰합니다.")

    render_daemon_controls("bat_daemon")
    render_bat_target_panel()
    render_live_daemon_panel("bat_daemon")
    with st.expander("최근 Daemon LLM 비용 기록", expanded=False):
        render_recent_llm_usage_runs(st.session_state.user_id, run_type=["daemon-refresh", "daemon-trigger"], limit=20)


def render_backtest_dashboard() -> None:
    render_backtest_daemon_panel("backtest")


def render_wallet_dashboard() -> None:
    st.subheader("Wallet")
    st.caption("dry-run과 backtest에서 사용할 지갑을 선택하고, 현재 DB 지갑 상태를 확인합니다.")

    render_wallet_control_panel("wallet")
