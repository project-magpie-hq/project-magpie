import time
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bat_daemon.utils.backtest import BACKTEST_CANDLE_INTERVAL, BACKTEST_REPLAY_MODES, DEFAULT_BACKTEST_REPLAY_MODE
from dashboard.common import pretty_json

from .backtest_runtime import (
    drain_backtest_event_queue,
    ensure_backtest_stream_state,
    load_cached_strategy,
    start_backtest_worker,
)
from .common import (
    render_session_stats,
    render_signal_table,
    render_target_snapshot,
    render_tick_table,
    render_wallet_snapshot,
    sort_rows_by_datetime,
)

PROCESS_RERUN_INTERVAL_SECONDS = 1.5
REPORT_DIR = Path("reports/backtests")


def _format_metric_price(value: Any) -> str:
    return f"{value:,.0f}" if pd.notna(value) else "-"


def _coerce_signal_rows(
    signals: list[dict[str, Any]], process_events: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any, Any]] = set()

    for signal in signals:
        row = dict(signal)
        key = (row.get("event_time"), row.get("target_coin"), row.get("signal_type"), row.get("price"))
        rows.append(row)
        seen.add(key)

    for event in process_events or []:
        raw = event.get("raw", {})
        if raw.get("event_type") not in {"signal", "trade_executed"}:
            continue

        row = {
            "event_time": raw.get("event_time"),
            "target_coin": raw.get("target_coin") or raw.get("coin"),
            "signal_type": raw.get("signal_type"),
            "price": raw.get("price"),
            "event_reason": raw.get("event_reason"),
            "result_status": raw.get("result_status"),
            "executed_volume": raw.get("executed_volume"),
        }
        key = (row.get("event_time"), row.get("target_coin"), row.get("signal_type"), row.get("price"))
        if key not in seen:
            rows.append(row)
            seen.add(key)

    return rows


def _build_tick_signal_chart(
    tick_rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    selected_coin: str,
) -> tuple[go.Figure | None, pd.DataFrame]:
    coin_ticks = [row for row in tick_rows if row.get("coin") == selected_coin]
    if not coin_ticks:
        return None, pd.DataFrame()

    tick_df = pd.DataFrame(coin_ticks).copy()
    tick_df["candle_time_dt"] = pd.to_datetime(tick_df["candle_time"], errors="coerce")
    tick_df = tick_df.sort_values("candle_time_dt", ascending=True)

    signal_df = pd.DataFrame([signal for signal in signals if signal.get("target_coin") == selected_coin]).copy()
    if not signal_df.empty:
        signal_df["event_time_dt"] = pd.to_datetime(signal_df["event_time"], errors="coerce")
        signal_df["signal_label"] = signal_df["signal_type"].astype(str)

    fig = go.Figure()
    added_series = 0
    for column_name, label, color, width, dash in [
        ("trade_price", "Trade Price", "#0f172a", 2.6, "solid"),
        ("buy_lower", "Buy Lower", "#2563eb", 1.7, "dash"),
        ("buy_upper", "Buy Upper", "#60a5fa", 1.7, "dash"),
        ("take_profit", "Take Profit", "#16a34a", 1.7, "dot"),
        ("stop_loss", "Stop Loss", "#dc2626", 1.7, "dot"),
    ]:
        if column_name not in tick_df.columns:
            continue

        series_df = tick_df[["candle_time_dt", "candle_time", column_name]].dropna()
        if series_df.empty:
            continue

        fig.add_trace(
            go.Scattergl(
                x=series_df["candle_time_dt"],
                y=series_df[column_name],
                mode="lines",
                name=label,
                line={"color": color, "width": width, "dash": dash},
                customdata=series_df[["candle_time"]],
                hovertemplate=(f"Time: %{{customdata[0]}}<br>{label}: %{{y:,.2f}}<extra></extra>"),
            )
        )
        added_series += 1

    if added_series == 0:
        return None, tick_df

    if not signal_df.empty:
        for signal_label, color, symbol in [
            ("BUY", "#16a34a", "triangle-up"),
            ("SELL", "#dc2626", "triangle-down"),
        ]:
            marker_df = signal_df[signal_df["signal_label"] == signal_label].dropna(subset=["event_time_dt", "price"])
            if marker_df.empty:
                continue

            for column_name in ["event_time", "event_reason", "result_status", "executed_volume"]:
                if column_name not in marker_df.columns:
                    marker_df[column_name] = ""
            customdata = marker_df[["event_time", "event_reason", "result_status", "executed_volume"]].fillna("")
            fig.add_trace(
                go.Scatter(
                    x=marker_df["event_time_dt"],
                    y=marker_df["price"],
                    mode="markers",
                    name=signal_label,
                    marker={"color": color, "size": 13, "symbol": symbol, "line": {"color": "white", "width": 1}},
                    customdata=customdata,
                    hovertemplate=(
                        "Time: %{customdata[0]}<br>"
                        f"Signal: {signal_label}<br>"
                        "Price: %{y:,.2f}<br>"
                        "Reason: %{customdata[1]}<br>"
                        "Status: %{customdata[2]}<br>"
                        "Volume: %{customdata[3]}<extra></extra>"
                    ),
                )
            )

    fig.update_layout(
        height=520,
        hovermode="x unified",
        margin={"l": 12, "r": 12, "t": 18, "b": 12},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis={
            "title": "Tick Time",
            "rangeslider": {"visible": True, "thickness": 0.08},
        },
        yaxis={"title": "Price", "tickformat": ","},
    )
    return fig, tick_df


def render_tick_signal_plot(
    tick_rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    namespace: str,
) -> None:
    if not tick_rows:
        st.caption("시각화할 tick 데이터가 없습니다.")
        return

    available_coins = sorted({str(row.get("coin")) for row in tick_rows if row.get("coin")})
    if not available_coins:
        st.caption("시각화할 코인 정보가 없습니다.")
        return

    default_coin = st.session_state.get(f"{namespace}_result_plot_coin")
    if default_coin not in available_coins:
        default_coin = available_coins[0]

    selected_coin = st.selectbox(
        "시각화 코인",
        options=available_coins,
        index=available_coins.index(default_coin),
        key=f"{namespace}_result_plot_coin_widget",
        help="코인별 가격 흐름, 타점 기준값, BUY/SELL 시점을 함께 봅니다.",
    )
    st.session_state[f"{namespace}_result_plot_coin"] = selected_coin

    chart, tick_df = _build_tick_signal_chart(tick_rows, signals, selected_coin)
    if chart is None or tick_df.empty:
        st.caption("선택한 코인의 tick 데이터가 없습니다.")
        return

    st.plotly_chart(
        chart,
        width="stretch",
        config={
            "displaylogo": False,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )

    latest_tick = tick_df.iloc[-1]
    summary_cols = st.columns(5)
    summary_cols[0].metric("현재가", f"{latest_tick['trade_price']:,.0f}")
    summary_cols[1].metric("Buy Lower", _format_metric_price(latest_tick["buy_lower"]))
    summary_cols[2].metric("Buy Upper", _format_metric_price(latest_tick["buy_upper"]))
    summary_cols[3].metric("Take Profit", _format_metric_price(latest_tick["take_profit"]))
    summary_cols[4].metric("Stop Loss", _format_metric_price(latest_tick["stop_loss"]))


def _live_tick_rows_from_events(process_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sort_rows_by_datetime(
        [row["tick_row"] for row in process_events if row.get("tick_row")],
        "candle_time",
        ascending=True,
    )


def _artifact_safe(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    return safe.strip("-") or "backtest"


def _to_report_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _to_report_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_report_data(item) for item in value]
    if isinstance(value, tuple):
        return [_to_report_data(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _write_backtest_report_files(
    result: dict[str, Any],
    tick_rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    selected_coin: str | None,
) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backtest_id = _artifact_safe(str(result.get("backtest_id") or result.get("wallet_user_id") or "backtest"))
    selected_coin_slug = _artifact_safe(selected_coin or "all")
    base_path = REPORT_DIR / f"{timestamp}-{backtest_id}-{selected_coin_slug}"
    json_path = base_path.with_suffix(".json")
    html_path = base_path.with_suffix(".html")

    report_payload = {
        "saved_at": timestamp,
        "selected_coin": selected_coin,
        "summary": {
            "strategy_user_id": result.get("strategy_user_id"),
            "backtest_id": result.get("backtest_id"),
            "wallet_user_id": result.get("wallet_user_id"),
            "selected_target_coins": result.get("selected_target_coins"),
            "processed_ticks": result.get("processed_ticks"),
            "visible_tick_rows": len(tick_rows),
            "signal_count": len(signals),
            "loaded_candles": result.get("loaded_candles"),
        },
        "session_stats": _to_report_data(result.get("session_stats")),
        "wallet": _to_report_data(result.get("wallet")),
        "initial_targets": _to_report_data(result.get("initial_targets")),
        "final_targets": _to_report_data(result.get("final_targets")),
        "generated_targets": _to_report_data(result.get("generated_targets")),
        "signals": _to_report_data(signals),
        "tick_rows": _to_report_data(tick_rows),
    }
    json_path.write_text(pretty_json(report_payload), encoding="utf-8")

    chart_html = "<p>시각화할 tick 데이터가 없습니다.</p>"
    if selected_coin:
        chart, _ = _build_tick_signal_chart(tick_rows, signals, selected_coin)
        if chart is not None:
            chart_html = chart.to_html(full_html=False, include_plotlyjs="cdn", config={"displaylogo": False})

    summary_html = escape(pretty_json(report_payload["summary"]))
    stats_html = escape(pretty_json(result.get("session_stats")))
    signals_html = escape(pretty_json(signals))
    targets_html = escape(pretty_json(result.get("final_targets")))
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Magpie Backtest Report - {escape(backtest_id)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #111827; }}
    h1, h2 {{ margin-bottom: 8px; }}
    section {{ margin-top: 28px; }}
    pre {{ background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Magpie Backtest Report</h1>
  <p>Saved at {escape(timestamp)} / selected coin {escape(selected_coin or "-")}</p>
  <section>
    <h2>Tick / Signal Plot</h2>
    {chart_html}
  </section>
  <section>
    <h2>Summary</h2>
    <pre>{summary_html}</pre>
  </section>
  <section>
    <h2>Session Stats</h2>
    <pre>{stats_html}</pre>
  </section>
  <section>
    <h2>Signals</h2>
    <pre>{signals_html}</pre>
  </section>
  <section>
    <h2>Final Targets</h2>
    <pre>{targets_html}</pre>
  </section>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path, json_path


def render_backtest_report_save_controls(
    result: dict[str, Any],
    tick_rows: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    namespace: str,
) -> None:
    available_coins = sorted({str(row.get("coin")) for row in tick_rows if row.get("coin")})
    selected_coin = st.session_state.get(f"{namespace}_result_plot_coin")
    if selected_coin not in available_coins:
        selected_coin = available_coins[0] if available_coins else None

    cols = st.columns([1, 2])
    if cols[0].button("백테스트 리포트 저장", key=f"{namespace}_save_report", disabled=not tick_rows):
        html_path, json_path = _write_backtest_report_files(result, tick_rows, signals, selected_coin)
        st.session_state[f"{namespace}_last_report_paths"] = {
            "html": str(html_path),
            "json": str(json_path),
        }

    report_paths = st.session_state.get(f"{namespace}_last_report_paths")
    if report_paths:
        cols[1].success(f"저장 완료: {report_paths['html']} / {report_paths['json']}")
        html_path = Path(report_paths["html"])
        if html_path.exists():
            st.download_button(
                "HTML 다운로드",
                data=html_path.read_bytes(),
                file_name=html_path.name,
                mime="text/html",
                key=f"{namespace}_download_report_html",
            )


def render_backtest_flow_dashboard(namespace: str, result: dict[str, Any] | None) -> None:
    process_events: list[dict[str, Any]] = st.session_state.get(f"{namespace}_process_events", [])
    is_running = st.session_state.get(f"{namespace}_backtest_running", False)
    tick_events = [row for row in process_events if row["raw"].get("event_type") == "tick_processed"]
    error_events = [row for row in process_events if row["category"] == "error"]

    final_tick_rows = sort_rows_by_datetime((result or {}).get("tick_rows", []), "candle_time", ascending=True)
    live_tick_rows = _live_tick_rows_from_events(process_events)
    tick_rows = live_tick_rows if is_running or not final_tick_rows else final_tick_rows
    signal_rows = _coerce_signal_rows((result or {}).get("signals", []), process_events)

    latest_event = process_events[-1] if process_events else None
    latest_tick = tick_events[-1] if tick_events else None
    total_ticks = latest_tick["raw"].get("total_ticks", 0) if latest_tick else (result or {}).get("processed_ticks", 0)
    processed_ticks = (
        latest_tick["raw"].get("processed_ticks", 0) if latest_tick else (result or {}).get("processed_ticks", 0)
    )

    cols = st.columns(5)
    cols[0].metric("상태", "Running" if is_running else ("Completed" if result else "Idle"))
    cols[1].metric("처리 tick", f"{processed_ticks:,}")
    cols[2].metric("표시 tick", f"{len(tick_rows):,}")
    cols[3].metric("신호", f"{len(signal_rows):,}")
    cols[4].metric("최근 이벤트", latest_event["label"] if latest_event else "-")
    st.progress(
        min((processed_ticks / total_ticks) if total_ticks else 0.0, 1.0),
        text=f"tick 진행률 {processed_ticks:,} / {total_ticks:,}" if total_ticks else "준비 중",
    )
    if latest_event:
        st.caption(latest_event["message"])

    if error_events:
        latest_error = error_events[-1]
        st.error(latest_error["message"])
        traceback_text = latest_error["raw"].get("traceback")
        if traceback_text:
            with st.expander("오류 상세", expanded=False):
                st.code(traceback_text, language="python")

    render_tick_signal_plot(tick_rows, signal_rows, namespace)

    if result and not result.get("error"):
        render_backtest_report_save_controls(result, final_tick_rows, result.get("signals", []), namespace)
        st.divider()
        render_session_stats(result.get("session_stats"), "백테스트 결과")

        st.markdown("##### 발생 신호")
        render_signal_table(result.get("signals", []), result.get("final_targets", {}))

        render_wallet_snapshot(result.get("wallet"), "백테스트 후 DB 지갑 상태")

        with st.expander("초기/최종 target 상태", expanded=False):
            left, right = st.columns(2)
            with left:
                render_target_snapshot(result.get("initial_targets", {}), "초기 target 상태")
            with right:
                render_target_snapshot(result.get("final_targets", {}), "재생 후 target 상태")

        with st.expander("상세 데이터", expanded=False):
            st.caption(
                f"원본 전략 user_id: `{result.get('strategy_user_id')}` / "
                f"백테스트 user_id: `{result.get('backtest_id') or result.get('wallet_user_id')}`"
            )
            if result.get("selected_target_coins") is not None:
                st.caption(f"선택된 target_coins: `{', '.join(result.get('selected_target_coins') or [])}`")
            st.markdown("###### 로드된 캔들 수")
            st.code(pretty_json(result.get("loaded_candles", {})), language="json")
            st.markdown("###### 생성된 backtest monitoring_targets")
            st.code(pretty_json(result.get("generated_targets", [])), language="json")
            st.markdown("###### Tick 변화와 조건 판정")
            render_tick_table(final_tick_rows)
    elif result and result.get("error"):
        st.warning(result["error"])
    elif not tick_rows:
        st.caption(
            "백테스트를 시작하면 이 영역에서 tick 가격, 매수/매도 기준선, BUY/SELL 시점이 실시간으로 그려집니다."
        )


def render_backtest_daemon_panel(namespace: str = "backtest") -> None:
    ensure_backtest_stream_state(namespace)
    drain_backtest_event_queue(namespace)

    col_a, col_b = st.columns(2)
    strategy_user_id = col_a.text_input(
        "Strategy User ID",
        value=st.session_state.get("backtest_strategy_user_id_value", st.session_state.user_id),
        key=f"{namespace}_strategy_user_id",
        help="원본 strategies를 복사할 user_id입니다.",
    )
    backtest_id = col_b.text_input(
        "Backtest ID",
        value=st.session_state.get("backtest_id_value", "backtest_001"),
        key=f"{namespace}_backtest_id",
        help="전략/지갑/타점을 격리 저장할 백테스트 전용 user_id입니다.",
    )
    st.session_state.backtest_strategy_user_id_value = strategy_user_id
    st.session_state.backtest_id_value = backtest_id

    source_strategy = None
    strategy_target_coins: list[str] = []
    if strategy_user_id.strip():
        try:
            source_strategy = load_cached_strategy(namespace, strategy_user_id)
        except Exception as exc:
            st.warning(f"원본 전략을 불러오지 못했습니다: {exc}")
        else:
            strategy_target_coins = list(source_strategy.get("target_coins") or []) if source_strategy else []

    default_selected_coins = st.session_state.get(f"{namespace}_selected_target_coins") or strategy_target_coins
    default_selected_coins = [coin for coin in default_selected_coins if coin in strategy_target_coins]
    selected_target_coins = st.multiselect(
        "백테스트 대상 코인",
        options=strategy_target_coins,
        default=default_selected_coins,
        key=f"{namespace}_selected_target_coins_widget",
        help="원본 전략 target_coins 중 실제로 backtest monitoring target을 생성할 코인만 선택합니다.",
        placeholder="원본 전략을 불러오면 선택 가능한 코인이 표시됩니다.",
    )
    st.session_state[f"{namespace}_selected_target_coins"] = selected_target_coins

    if source_strategy is None:
        st.caption("원본 전략 user_id를 입력하면 선택 가능한 target_coins를 불러옵니다.")
    elif not strategy_target_coins:
        st.warning("원본 전략에 target_coins가 없습니다.")

    col_c, col_d, col_e, col_f = st.columns([1, 1, 1, 1.1])
    start = col_c.text_input("시작 일시", value="2026-06-01 00:00:00", key=f"{namespace}_start")
    end = col_d.text_input("종료 일시", value="2026-07-01 00:00:00", key=f"{namespace}_end")
    initial_balance = col_e.number_input(
        "초기 KRW", min_value=0.0, value=100000000.0, step=1000000.0, format="%.0f", key=f"{namespace}_initial_balance"
    )
    replay_mode = col_f.selectbox(
        "재생 모드",
        options=list(BACKTEST_REPLAY_MODES),
        index=list(BACKTEST_REPLAY_MODES).index(
            st.session_state.get(f"{namespace}_replay_mode", DEFAULT_BACKTEST_REPLAY_MODE)
            if st.session_state.get(f"{namespace}_replay_mode", DEFAULT_BACKTEST_REPLAY_MODE) in BACKTEST_REPLAY_MODES
            else DEFAULT_BACKTEST_REPLAY_MODE
        ),
        key=f"{namespace}_replay_mode_widget",
        help="close_only는 각 1분봉 종가를 기준으로 재생합니다. ohlc_path는 synthetic 1시간 봉의 open/high/low/close 경로를 재생합니다.",
    )
    st.session_state[f"{namespace}_replay_mode"] = replay_mode
    st.caption(
        f"백테스트 데이터 해상도: `{BACKTEST_CANDLE_INTERVAL}` / 재생 모드: `{replay_mode}` / "
        "CLOSE 조건은 매 분 시점의 최근 60개 1분봉을 묶은 synthetic 1시간 봉 기준으로 판정합니다."
    )

    is_running = st.session_state.get(f"{namespace}_backtest_running", False)
    if st.button("백테스트 실행", width="stretch", key=f"{namespace}_run_backtest", disabled=is_running):
        try:
            if strategy_target_coins and not selected_target_coins:
                raise ValueError("백테스트 대상 코인을 최소 1개 이상 선택하세요.")
            start_backtest_worker(
                namespace,
                strategy_user_id,
                backtest_id,
                start,
                end,
                float(initial_balance),
                selected_target_coins or None,
                replay_mode=replay_mode,
            )
        except Exception as exc:
            st.session_state.bat_backtest_result = {"error": str(exc)}

    result = st.session_state.get("bat_backtest_result")
    if st.session_state.get(f"{namespace}_backtest_running", False):
        st.info("백테스트가 실행 중입니다. plot에서 tick 흐름과 BUY/SELL 시점을 실시간으로 확인할 수 있습니다.")

    render_backtest_flow_dashboard(namespace, result)

    if st.session_state.get(f"{namespace}_backtest_running", False):
        time.sleep(PROCESS_RERUN_INTERVAL_SECONDS)
        st.rerun()
