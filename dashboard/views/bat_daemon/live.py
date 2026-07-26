import asyncio
from typing import Any

import pandas as pd
import streamlit as st

from bat_daemon.market_data.upbit_ws import connect_upbit_ws, receive_candle_tick, subscribe_candles
from bat_daemon.run import BatDaemon
from bat_daemon.session_stats import build_session_stats_from_signal_history
from dashboard.asyncio_utils import run_async_task
from dashboard.common import pretty_json
from magpie_agent.tools.wallet import fetch_wallet_by_user, register_wallet

from .common import (
    diff_target_snapshots,
    render_session_stats,
    render_signal_table,
    render_target_snapshot,
    render_tick_table,
    render_wallet_snapshot,
    target_snapshot,
    tick_event_row,
)


async def collect_live_daemon_sample(user_id: str, max_ticks: int, timeout_seconds: int) -> dict[str, Any]:
    wallet_user_id = st.session_state.wallet_user_id or user_id
    bat = BatDaemon(user_id, wallet_user_id=wallet_user_id, dry_run=True, enable_graph=False)
    await bat.load_targets_from_db_once()

    if not bat.watching_coins:
        return {
            "targets": {},
            "tick_rows": [],
            "signals": [],
            "error": "monitoring target이 없습니다.",
            "wallet_user_id": bat.wallet_user_id,
        }

    tick_rows: list[dict[str, Any]] = []
    async with connect_upbit_ws() as websocket:
        await subscribe_candles(websocket, user_id, bat.watching_coins)

        for _ in range(max_ticks):
            try:
                coin, tick = await asyncio.wait_for(receive_candle_tick(websocket), timeout=timeout_seconds)
            except TimeoutError:
                break
            if not coin:
                continue

            target_before = bat.active_targets[coin].model_copy(deep=True) if coin in bat.active_targets else None
            signal_count_before = len(bat.signal_history)
            await bat.process_candle_tick(coin, tick)
            target_after = bat.active_targets.get(coin)
            new_signals = bat.signal_history[signal_count_before:]
            tick_rows.append(tick_event_row(coin, tick, target_before, target_after, new_signals, "live"))

    return {
        "targets": bat.active_targets,
        "tick_rows": tick_rows,
        "signals": bat.signal_history,
        "session_stats": build_session_stats_from_signal_history(bat.signal_history),
        "current_candles": bat.current_candles,
        "wallet": bat.simulated_wallet,
        "wallet_user_id": bat.wallet_user_id,
    }


def render_daemon_controls(namespace: str) -> None:
    st.markdown("#### 실행 설정")
    st.caption("Bat Daemon 샘플과 backtest에 필요한 monitoring target 식별자를 이 탭에서 직접 설정합니다.")

    new_user_id = st.text_input(
        "Target User ID",
        value=st.session_state.user_id,
        key=f"{namespace}_target_user_id",
        help="monitoring_targets를 조회할 user_id입니다.",
    )
    if new_user_id != st.session_state.user_id:
        st.session_state.user_id = new_user_id


def render_bat_target_panel() -> None:
    with st.spinner("DB monitoring_targets를 불러오는 중..."):
        bat = BatDaemon(
            st.session_state.user_id,
            wallet_user_id=st.session_state.wallet_user_id or st.session_state.user_id,
            dry_run=True,
            enable_graph=False,
        )
        run_async_task(bat.load_targets_from_db_once())

    current_snapshot = target_snapshot(bat.active_targets)
    changes = diff_target_snapshots(st.session_state.get("bat_target_snapshot"), current_snapshot)

    cols = st.columns(4)
    cols[0].metric("Targets", len(bat.active_targets))
    cols[1].metric("Watching Coins", len(bat.watching_coins))
    cols[2].metric("Changed Fields", len(changes))
    cols[3].metric("Mode", "dry-run")
    st.caption(f"Target user_id: `{st.session_state.user_id}` / Wallet user_id: `{bat.wallet_user_id}`")

    render_target_snapshot(bat.active_targets, "DB monitoring_targets 현재 값")

    with st.expander("이전 새로고침 대비 변경 내역", expanded=bool(changes)):
        if changes:
            st.dataframe(pd.DataFrame(changes), width="stretch", hide_index=True)
        else:
            st.caption("이전 snapshot 대비 변경된 필드가 없습니다.")

    st.session_state.bat_target_snapshot = current_snapshot


def render_wallet_control_panel(namespace: str) -> None:
    st.markdown("#### 지갑 선택 및 생성")
    effective_wallet_user_id = st.session_state.wallet_user_id or st.session_state.user_id
    st.caption("Bat Daemon과 Backtest가 사용할 지갑을 이 탭에서 관리합니다.")

    new_wallet_user_id = st.text_input(
        "Wallet User ID",
        value=st.session_state.wallet_user_id,
        key=f"{namespace}_wallet_user_id",
        help="dry-run과 backtest에서 사용할 wallets 조회 user_id입니다. 비우면 Target User ID와 동일하게 사용됩니다.",
    )
    normalized_wallet_user_id = new_wallet_user_id.strip()
    if normalized_wallet_user_id != st.session_state.wallet_user_id:
        st.session_state.wallet_user_id = normalized_wallet_user_id
        effective_wallet_user_id = st.session_state.wallet_user_id or st.session_state.user_id

    st.caption(f"현재 선택된 지갑 user_id는 `{effective_wallet_user_id}` 입니다.")

    col_a, col_b = st.columns([1.3, 1])
    initial_balance = col_a.number_input(
        "새 지갑 초기 KRW",
        min_value=0.0,
        value=100000000.0,
        step=1000000.0,
        format="%.0f",
        key=f"{namespace}_initial_balance",
    )
    if col_b.button(
        f"지갑 생성 / 초기화 ({effective_wallet_user_id})", width="stretch", key=f"{namespace}_reset_wallet"
    ):
        with st.spinner("지갑을 생성하거나 초기화하는 중..."):
            try:
                wallet = run_async_task(register_wallet(effective_wallet_user_id, float(initial_balance)))
            except Exception as exc:
                st.exception(exc)
            else:
                st.success(f"`{effective_wallet_user_id}` 지갑 생성/초기화 완료. 현재 잔고: {wallet.balance:,.0f} KRW")
                st.session_state.bat_live_result = None
                st.session_state.bat_backtest_result = None

    try:
        fetched_wallet = run_async_task(fetch_wallet_by_user(effective_wallet_user_id))
    except Exception as exc:
        st.exception(exc)
    else:
        render_wallet_snapshot(fetched_wallet, "DB wallets 현재 값")


def render_live_daemon_panel(namespace: str = "bat_daemon") -> None:
    st.markdown("#### 실시간 tick 샘플")
    st.caption(
        "실제 DB target 및 Upbit websocket tick을 사용하되, 대시보드에서는 dry-run으로 조건만 판정합니다. "
        f"지갑은 `{st.session_state.wallet_user_id or st.session_state.user_id}` 기준으로 불러옵니다."
    )

    col_a, col_b = st.columns(2)
    max_ticks = col_a.number_input(
        "수집할 tick 개수", min_value=1, max_value=200, value=20, step=1, key=f"{namespace}_max_ticks"
    )
    timeout_seconds = col_b.number_input(
        "tick 수신 timeout(초)",
        min_value=3,
        max_value=120,
        value=20,
        step=1,
        key=f"{namespace}_timeout_seconds",
    )

    if st.button("실시간 tick 수집 시작", width="stretch", key=f"{namespace}_collect_live_ticks"):
        with st.spinner("Upbit websocket에서 tick을 수집하고 조건을 판정하는 중..."):
            try:
                st.session_state.bat_live_result = run_async_task(
                    collect_live_daemon_sample(st.session_state.user_id, int(max_ticks), int(timeout_seconds))
                )
            except Exception as exc:
                st.session_state.bat_live_result = {"error": str(exc), "tick_rows": [], "signals": [], "targets": {}}

    result = st.session_state.get("bat_live_result")
    if not result:
        return

    if result.get("error"):
        st.warning(result["error"])

    metric_cols = st.columns(3)
    metric_cols[0].metric("수집 tick", len(result.get("tick_rows", [])))
    metric_cols[1].metric("감지 신호", len(result.get("signals", [])))
    metric_cols[2].metric("마지막 캔들", len(result.get("current_candles", {})))
    st.caption(f"사용 지갑 user_id: `{result.get('wallet_user_id') or st.session_state.user_id}`")

    render_wallet_snapshot(result.get("wallet"), "실시간 dry-run 지갑 상태")
    render_session_stats(result.get("session_stats"), "실시간 run 세션 통계")

    st.markdown("##### Tick 변화와 조건 판정")
    render_tick_table(result.get("tick_rows", []))

    st.markdown("##### 발생 신호")
    render_signal_table(result.get("signals", []), result.get("targets", {}))

    with st.expander("현재 메모리 캔들", expanded=False):
        st.code(pretty_json(result.get("current_candles", {})), language="json")
