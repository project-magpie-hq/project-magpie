import asyncio
from typing import Any

import pandas as pd
import streamlit as st

from bat_daemon.backtest import _candle_path, _load_historical_data, _to_upbit_tick
from bat_daemon.market_data.upbit_ws import connect_upbit_ws, receive_candle_tick, subscribe_candles
from bat_daemon.run import BatDaemon
from dashboard.common import pretty_json
from db.entity import TargetEntity


def target_to_row(target: TargetEntity) -> dict[str, Any]:
    return {
        "coin": target.target_coin,
        "status": str(target.status),
        "trigger": str(target.trigger_basis),
        "buy_lower": target.buy_price_lower_limit,
        "buy_upper": target.buy_price_upper_limit,
        "take_profit": target.take_profit_price,
        "stop_loss": target.stop_loss_price,
        "min_volume": target.min_volume_threshold,
        "requires_bullish": target.requires_bullish_close,
        "reason": target.reason,
    }


def target_snapshot(targets: dict[str, TargetEntity]) -> dict[str, dict[str, Any]]:
    return {coin: target_to_row(target) for coin, target in sorted(targets.items())}


def render_target_snapshot(targets: dict[str, TargetEntity], title: str) -> None:
    st.markdown(f"#### {title}")
    rows = list(target_snapshot(targets).values())
    if not rows:
        st.warning("현재 DB에 monitoring target이 없습니다.")
        return

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with st.expander("Raw target JSON", expanded=False):
        raw_targets = {coin: target.model_dump(mode="json") for coin, target in targets.items()}
        st.code(pretty_json(raw_targets), language="json")


def diff_target_snapshots(
    before: dict[str, dict[str, Any]] | None,
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not before:
        return []

    changes: list[dict[str, Any]] = []
    for coin in sorted(set(before) | set(after)):
        if coin not in before:
            changes.append({"coin": coin, "field": "_target", "before": None, "after": "added"})
            continue
        if coin not in after:
            changes.append({"coin": coin, "field": "_target", "before": "removed", "after": None})
            continue

        for field, after_value in after[coin].items():
            before_value = before[coin].get(field)
            if before_value != after_value:
                changes.append({"coin": coin, "field": field, "before": before_value, "after": after_value})
    return changes


def signal_context_row(signal: dict[str, Any], target: TargetEntity | None) -> dict[str, Any]:
    row = {
        "event_time": signal.get("event_time"),
        "coin": signal.get("target_coin"),
        "signal": signal.get("signal_type"),
        "price": signal.get("price"),
        "reason": signal.get("event_reason"),
        "target_status": signal.get("target_status"),
        "result_status": signal.get("result_status"),
    }
    if target:
        row.update(
            {
                "trigger": str(target.trigger_basis),
                "buy_lower": target.buy_price_lower_limit,
                "buy_upper": target.buy_price_upper_limit,
                "take_profit": target.take_profit_price,
                "stop_loss": target.stop_loss_price,
                "min_volume": target.min_volume_threshold,
            }
        )
    return row


def tick_event_row(
    coin: str,
    tick: dict[str, Any],
    target_before: TargetEntity | None,
    target_after: TargetEntity | None,
    signals: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    target_for_thresholds = target_before or target_after
    row = {
        "source": source,
        "coin": coin,
        "candle_time": tick.get("candle_date_time_kst"),
        "trade_price": tick.get("trade_price"),
        "opening_price": tick.get("opening_price"),
        "high_price": tick.get("high_price"),
        "low_price": tick.get("low_price"),
        "volume": tick.get("candle_acc_trade_volume"),
        "status_before": str(target_before.status) if target_before else None,
        "status_after": str(target_after.status) if target_after else None,
        "signal": ", ".join(signal.get("signal_type", "") for signal in signals) or None,
        "event_reason": ", ".join(signal.get("event_reason", "") for signal in signals) or None,
    }
    if target_for_thresholds:
        row.update(
            {
                "trigger": str(target_for_thresholds.trigger_basis),
                "buy_lower": target_for_thresholds.buy_price_lower_limit,
                "buy_upper": target_for_thresholds.buy_price_upper_limit,
                "take_profit": target_for_thresholds.take_profit_price,
                "stop_loss": target_for_thresholds.stop_loss_price,
            }
        )
    return row


async def collect_live_daemon_sample(user_id: str, max_ticks: int, timeout_seconds: int) -> dict[str, Any]:
    bat = BatDaemon(user_id, dry_run=True, enable_graph=False)
    await bat.load_targets_from_db_once()

    if not bat.watching_coins:
        return {"targets": {}, "tick_rows": [], "signals": [], "error": "monitoring target이 없습니다."}

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

            target_before = bat.active_targets.get(coin).model_copy(deep=True) if coin in bat.active_targets else None
            signal_count_before = len(bat.signal_history)
            await bat.process_candle_tick(coin, tick)
            target_after = bat.active_targets.get(coin)
            new_signals = bat.signal_history[signal_count_before:]
            tick_rows.append(tick_event_row(coin, tick, target_before, target_after, new_signals, "live"))

    return {
        "targets": bat.active_targets,
        "tick_rows": tick_rows,
        "signals": bat.signal_history,
        "current_candles": bat.current_candles,
    }


async def collect_backtest_daemon_sample(
    user_id: str,
    start: str,
    end: str,
    max_tick_rows: int,
) -> dict[str, Any]:
    bat = BatDaemon(user_id, dry_run=True, enable_graph=False)
    await bat.load_targets_from_db_once()
    initial_targets = {coin: target.model_copy(deep=True) for coin, target in bat.active_targets.items()}

    if not bat.watching_coins:
        return backtest_result(initial_targets, bat.active_targets, "monitoring target이 없습니다.")

    historical_data = await _load_historical_data(bat.watching_coins, start, end)
    if not historical_data:
        return backtest_result(initial_targets, bat.active_targets, "로드된 과거 캔들이 없습니다.")

    tick_rows: list[dict[str, Any]] = []
    processed_ticks = 0
    timeline = sorted(set().union(*[df.index for df in historical_data.values()]))

    for candle_time in timeline:
        for coin, df in historical_data.items():
            if candle_time not in df.index:
                continue

            candle = df.loc[candle_time]
            for _, trade_price in _candle_path(candle):
                tick = _to_upbit_tick(coin, candle_time, candle, trade_price)
                target_before = bat.active_targets.get(coin).model_copy(deep=True) if coin in bat.active_targets else None
                signal_count_before = len(bat.signal_history)
                await bat.process_candle_tick(coin, tick)
                target_after = bat.active_targets.get(coin)
                new_signals = bat.signal_history[signal_count_before:]
                processed_ticks += 1

                if len(tick_rows) < max_tick_rows or new_signals:
                    tick_rows.append(tick_event_row(coin, tick, target_before, target_after, new_signals, "backtest"))

    await bat.flush_current_candles()

    return {
        "initial_targets": initial_targets,
        "final_targets": bat.active_targets,
        "tick_rows": tick_rows,
        "signals": bat.signal_history,
        "processed_ticks": processed_ticks,
        "loaded_candles": {coin: len(df) for coin, df in historical_data.items()},
    }


def backtest_result(
    initial_targets: dict[str, TargetEntity],
    final_targets: dict[str, TargetEntity],
    error: str,
) -> dict[str, Any]:
    return {
        "initial_targets": initial_targets,
        "final_targets": final_targets,
        "tick_rows": [],
        "signals": [],
        "processed_ticks": 0,
        "error": error,
    }


def render_signal_table(signals: list[dict[str, Any]], targets: dict[str, TargetEntity]) -> None:
    if not signals:
        st.caption("아직 조건을 만족한 BUY/SELL 신호가 없습니다.")
        return

    rows = [signal_context_row(signal, targets.get(signal.get("target_coin"))) for signal in signals]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_tick_table(tick_rows: list[dict[str, Any]]) -> None:
    if not tick_rows:
        st.caption("수집된 tick 이벤트가 없습니다.")
        return

    st.dataframe(pd.DataFrame(tick_rows), use_container_width=True, hide_index=True)


def render_bat_target_panel() -> None:
    with st.spinner("DB monitoring_targets를 불러오는 중..."):
        bat = BatDaemon(st.session_state.user_id, dry_run=True, enable_graph=False)
        asyncio.run(bat.load_targets_from_db_once())

    current_snapshot = target_snapshot(bat.active_targets)
    changes = diff_target_snapshots(st.session_state.get("bat_target_snapshot"), current_snapshot)

    cols = st.columns(4)
    cols[0].metric("Targets", len(bat.active_targets))
    cols[1].metric("Watching Coins", len(bat.watching_coins))
    cols[2].metric("Changed Fields", len(changes))
    cols[3].metric("Mode", "dry-run")

    render_target_snapshot(bat.active_targets, "DB monitoring_targets 현재 값")

    with st.expander("이전 새로고침 대비 변경 내역", expanded=bool(changes)):
        if changes:
            st.dataframe(pd.DataFrame(changes), use_container_width=True, hide_index=True)
        else:
            st.caption("이전 snapshot 대비 변경된 필드가 없습니다.")

    st.session_state.bat_target_snapshot = current_snapshot


def render_live_daemon_panel() -> None:
    st.markdown("#### 실시간 tick 샘플")
    st.caption("실제 DB target 및 Upbit websocket tick을 사용하되, 대시보드에서는 dry-run으로 조건만 판정합니다.")

    col_a, col_b = st.columns(2)
    max_ticks = col_a.number_input("수집할 tick 개수", min_value=1, max_value=200, value=20, step=1)
    timeout_seconds = col_b.number_input("tick 수신 timeout(초)", min_value=3, max_value=120, value=20, step=1)

    if st.button("실시간 tick 수집 시작", use_container_width=True):
        with st.spinner("Upbit websocket에서 tick을 수집하고 조건을 판정하는 중..."):
            try:
                st.session_state.bat_live_result = asyncio.run(
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

    st.markdown("##### Tick 변화와 조건 판정")
    render_tick_table(result.get("tick_rows", []))

    st.markdown("##### 발생 신호")
    render_signal_table(result.get("signals", []), result.get("targets", {}))

    with st.expander("현재 메모리 캔들", expanded=False):
        st.code(pretty_json(result.get("current_candles", {})), language="json")


def render_backtest_daemon_panel() -> None:
    st.markdown("#### 과거 캔들 백테스트")
    st.caption("DB의 현재 monitoring target을 기준으로 과거 1시간봉을 가상 tick으로 재생합니다.")

    col_a, col_b, col_c = st.columns([1, 1, 1])
    start = col_a.text_input("시작 일시", value="2024-01-01 00:00:00")
    end = col_b.text_input("종료 일시", value="2024-02-01 00:00:00")
    max_tick_rows = col_c.number_input("표시할 tick row 상한", min_value=20, max_value=5000, value=500, step=20)

    if st.button("백테스트 실행", use_container_width=True):
        with st.spinner("과거 캔들을 로드하고 BatDaemon 판정 로직으로 재생하는 중..."):
            try:
                st.session_state.bat_backtest_result = asyncio.run(
                    collect_backtest_daemon_sample(st.session_state.user_id, start, end, int(max_tick_rows))
                )
            except Exception as exc:
                st.session_state.bat_backtest_result = backtest_result({}, {}, str(exc))

    result = st.session_state.get("bat_backtest_result")
    if not result:
        return

    if result.get("error"):
        st.warning(result["error"])

    metric_cols = st.columns(4)
    metric_cols[0].metric("처리 tick", f"{result.get('processed_ticks', 0):,}")
    metric_cols[1].metric("표시 tick", f"{len(result.get('tick_rows', [])):,}")
    metric_cols[2].metric("감지 신호", f"{len(result.get('signals', [])):,}")
    metric_cols[3].metric("로드 캔들", f"{sum(result.get('loaded_candles', {}).values()):,}")

    with st.expander("로드된 캔들 수", expanded=False):
        st.code(pretty_json(result.get("loaded_candles", {})), language="json")

    left, right = st.columns(2)
    with left:
        render_target_snapshot(result.get("initial_targets", {}), "초기 target 상태")
    with right:
        render_target_snapshot(result.get("final_targets", {}), "재생 후 target 상태")

    st.markdown("##### Tick 변화와 조건 판정")
    render_tick_table(result.get("tick_rows", []))

    st.markdown("##### 발생 신호")
    render_signal_table(result.get("signals", []), result.get("final_targets", {}))


def render_bat_daemon_dashboard() -> None:
    st.subheader("Bat Daemon Monitor")
    st.caption("DB monitoring target, 실시간/과거 tick 변화, 조건 발동 지점을 dry-run으로 관찰합니다.")

    render_bat_target_panel()

    live_tab, backtest_tab = st.tabs(["실시간 run.py 샘플", "backtest.py 재생"])
    with live_tab:
        render_live_daemon_panel()
    with backtest_tab:
        render_backtest_daemon_panel()
