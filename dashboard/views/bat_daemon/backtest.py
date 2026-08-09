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
from dashboard.llm_usage import render_llm_usage_metrics

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
CUSTOM_BENCHMARK_LABEL = "직접 입력"
BACKTEST_BENCHMARK_PERIODS: dict[str, tuple[str, str]] = {
    "강력 상승장": ("2024-11-05 00:00:00", "2024-11-26 23:59:00"),
    "급격 하락장": ("2025-10-06 00:00:00", "2025-10-27 23:59:00"),
    "지루한 횡보장": ("2024-08-09 00:00:00", "2024-08-30 23:59:00"),
    "고변동 급락장": ("2026-01-20 00:00:00", "2026-02-06 23:59:00"),
}


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


def _format_report_number(value: Any, digits: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,.{digits}f}"


def _format_report_cost(value: Any) -> str:
    try:
        return f"${float(value):,.6f}"
    except (TypeError, ValueError):
        return "$0.000000"


def _html_cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return _format_report_number(value, 6).rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, list):
        return ", ".join(escape(str(item)) for item in value) or "-"
    if isinstance(value, dict):
        return escape(pretty_json(value))
    return escape(str(value))


def _metric_card(label: str, value: Any, accent: str = "#0f172a") -> str:
    return (
        '<div class="metric-card">'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value" style="color:{accent}">{_html_cell(value)}</div>'
        "</div>"
    )


def _html_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], empty_text: str) -> str:
    if not rows:
        return f'<p class="muted">{escape(empty_text)}</p>'

    header = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_html_cell(row.get(key))}</td>" for key, _ in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def _session_stats_to_html(session_stats: Any) -> str:
    stats = _to_report_data(session_stats) or {}
    cards = [
        _metric_card("Session Buy", stats.get("buy_count", 0), "#16a34a"),
        _metric_card("Session Sell", stats.get("sell_count", 0), "#dc2626"),
        _metric_card("Buy KRW", _format_report_number(stats.get("total_buy_krw", 0)), "#2563eb"),
        _metric_card("Sell KRW", _format_report_number(stats.get("total_sell_krw", 0)), "#f97316"),
    ]
    return f'<div class="metric-grid">{"".join(cards)}</div>'


def _llm_usage_to_html(usage: dict[str, Any] | None) -> str:
    usage = usage or {}
    cards = [
        _metric_card("LLM Calls", usage.get("total_calls", 0), "#0f172a"),
        _metric_card("Input Tokens", _format_report_number(usage.get("input_tokens", 0)), "#2563eb"),
        _metric_card("Output Tokens", _format_report_number(usage.get("output_tokens", 0)), "#7c3aed"),
        _metric_card("Total Tokens", _format_report_number(usage.get("total_tokens", 0)), "#0f766e"),
        _metric_card("Est. Cost", _format_report_cost(usage.get("estimated_cost_usd", 0.0)), "#ea580c"),
    ]
    by_agent_rows = [{"agent": key, **value} for key, value in sorted((usage.get("by_agent") or {}).items())]
    by_model_rows = [{"model": key, **value} for key, value in sorted((usage.get("by_model") or {}).items())]
    usage_columns = [
        ("calls", "Calls"),
        ("input_tokens", "Input"),
        ("output_tokens", "Output"),
        ("total_tokens", "Total"),
        ("estimated_cost_usd", "Est. Cost USD"),
    ]
    agent_table = _html_table(by_agent_rows, [("agent", "Agent"), *usage_columns], "Agent별 사용량이 없습니다.")
    model_table = _html_table(by_model_rows, [("model", "Model"), *usage_columns], "Model별 사용량이 없습니다.")
    return (
        f'<div class="metric-grid five">{"".join(cards)}</div>'
        '<div class="split">'
        f'<div><h3>Agent별</h3>{agent_table}</div>'
        f'<div><h3>Model별</h3>{model_table}</div>'
        "</div>"
        f'<p class="muted">{escape(str(usage.get("pricing_note") or "비용은 설정된 단가 기반의 추정치입니다."))}</p>'
    )


def _wallet_to_html(wallet: Any) -> str:
    wallet_data = _to_report_data(wallet) or {}
    assets = wallet_data.get("assets") or {}
    trade_history = wallet_data.get("trade_history") or []
    active_assets = [
        {"coin": coin, **asset}
        for coin, asset in sorted(assets.items())
        if isinstance(asset, dict) and float(asset.get("volume") or 0) > 0
    ]
    buy_count = sum(1 for trade in trade_history if str(trade.get("signal")) == "BUY")
    sell_count = sum(1 for trade in trade_history if str(trade.get("signal")) == "SELL")
    cards = [
        _metric_card("KRW Balance", _format_report_number(wallet_data.get("balance", 0)), "#0f172a"),
        _metric_card("Assets", len(active_assets), "#2563eb"),
        _metric_card("Buy Count", buy_count, "#16a34a"),
        _metric_card("Sell Count", sell_count, "#dc2626"),
    ]
    asset_table = _html_table(
        active_assets,
        [("coin", "Coin"), ("volume", "Volume"), ("avg_buy_price", "Avg Buy Price")],
        "보유 중인 코인 자산이 없습니다.",
    )
    trade_table = _html_table(
        trade_history[-30:],
        [
            ("executed_at", "Executed At"),
            ("market", "Market"),
            ("signal", "Signal"),
            ("price", "Price"),
            ("volume", "Volume"),
            ("total_price", "Total Price"),
        ],
        "체결 이력이 없습니다.",
    )
    return (
        f'<div class="metric-grid">{"".join(cards)}</div>'
        "<h3>보유 자산</h3>"
        f"{asset_table}"
        "<h3>최근 체결 이력</h3>"
        f"{trade_table}"
    )


def _targets_to_rows(targets: Any) -> list[dict[str, Any]]:
    target_data = _to_report_data(targets) or {}
    if isinstance(target_data, dict):
        iterable = target_data.items()
    elif isinstance(target_data, list):
        iterable = [(item.get("target_coin", idx) if isinstance(item, dict) else idx, item) for idx, item in enumerate(target_data)]
    else:
        return []

    rows = []
    for coin, target in iterable:
        if not isinstance(target, dict):
            continue
        rows.append(
            {
                "coin": target.get("target_coin") or coin,
                "status": target.get("status"),
                "trigger": target.get("trigger_basis"),
                "buy_lower": target.get("buy_price_lower_limit"),
                "buy_upper": target.get("buy_price_upper_limit"),
                "take_profit": target.get("take_profit_price"),
                "stop_loss": target.get("stop_loss_price"),
                "allocation": target.get("buy_allocation_pct"),
                "reason": target.get("reason"),
            }
        )
    return rows


def _signals_to_html(signals: list[dict[str, Any]]) -> str:
    return _html_table(
        signals,
        [
            ("event_time", "Event Time"),
            ("target_coin", "Coin"),
            ("signal_type", "Signal"),
            ("price", "Price"),
            ("event_reason", "Reason"),
            ("result_status", "Result"),
            ("executed_volume", "Volume"),
        ],
        "발생 신호가 없습니다.",
    )


def _backtest_report_body_html(report_payload: dict[str, Any], chart_html: str) -> str:
    summary = report_payload["summary"]
    loaded_candle_rows = [
        {"coin": coin, "candles": count}
        for coin, count in sorted((summary.get("loaded_candles") or {}).items())
    ]
    target_columns = [
        ("coin", "Coin"),
        ("status", "Status"),
        ("trigger", "Trigger"),
        ("buy_lower", "Buy Lower"),
        ("buy_upper", "Buy Upper"),
        ("take_profit", "Take Profit"),
        ("stop_loss", "Stop Loss"),
        ("allocation", "Allocation"),
        ("reason", "Reason"),
    ]
    raw_json_html = escape(pretty_json(report_payload))

    summary_cards = [
        _metric_card("Processed Ticks", _format_report_number(summary.get("processed_ticks", 0)), "#0f172a"),
        _metric_card("Visible Tick Rows", _format_report_number(summary.get("visible_tick_rows", 0)), "#2563eb"),
        _metric_card("Signal Count", summary.get("signal_count", 0), "#ea580c"),
        _metric_card("Benchmark", summary.get("benchmark_period") or "직접 입력", "#0f766e"),
    ]

    return f"""
  <section class="hero">
    <div>
      <p class="eyebrow">Magpie Backtest Report</p>
      <h1>{escape(str(summary.get("backtest_id") or "-"))}</h1>
      <p class="muted">Saved at {escape(str(report_payload.get("saved_at")))} / selected coin {escape(str(report_payload.get("selected_coin") or "-"))}</p>
    </div>
    <div class="hero-meta">
      <span>Strategy: {escape(str(summary.get("strategy_user_id") or "-"))}</span>
      <span>Wallet: {escape(str(summary.get("wallet_user_id") or "-"))}</span>
      <span>Targets: {escape(", ".join(summary.get("selected_target_coins") or []) or "-")}</span>
    </div>
  </section>
  <section>
    <h2>Tick / Signal Plot</h2>
    {chart_html}
  </section>
  <section>
    <h2>백테스트 결과</h2>
    <div class="metric-grid">{"".join(summary_cards)}</div>
    <h3>로드된 캔들 수</h3>
    {_html_table(loaded_candle_rows, [("coin", "Coin"), ("candles", "Candles")], "로드된 캔들 정보가 없습니다.")}
  </section>
  <section>
    <h2>세션 통계</h2>
    {_session_stats_to_html(report_payload.get("session_stats"))}
  </section>
  <section>
    <h2>LLM 사용량 / 예상 비용</h2>
    {_llm_usage_to_html(report_payload.get("llm_usage"))}
  </section>
  <section>
    <h2>발생 신호</h2>
    {_signals_to_html(report_payload.get("signals") or [])}
  </section>
  <section>
    <h2>백테스트 후 지갑 상태</h2>
    {_wallet_to_html(report_payload.get("wallet"))}
  </section>
  <section>
    <h2>초기 Target 상태</h2>
    {_html_table(_targets_to_rows(report_payload.get("initial_targets")), target_columns, "초기 target 정보가 없습니다.")}
  </section>
  <section>
    <h2>최종 Target 상태</h2>
    {_html_table(_targets_to_rows(report_payload.get("final_targets")), target_columns, "최종 target 정보가 없습니다.")}
  </section>
  <section>
    <details>
      <summary>Raw Report JSON</summary>
      <pre>{raw_json_html}</pre>
    </details>
  </section>
"""


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
            "benchmark_period": result.get("benchmark_period"),
            "processed_ticks": result.get("processed_ticks"),
            "visible_tick_rows": len(tick_rows),
            "signal_count": len(signals),
            "loaded_candles": result.get("loaded_candles"),
            "llm_usage": result.get("llm_usage"),
        },
        "session_stats": _to_report_data(result.get("session_stats")),
        "llm_usage": _to_report_data(result.get("llm_usage")),
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

    body_html = _backtest_report_body_html(report_payload, chart_html)
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Magpie Backtest Report - {escape(backtest_id)}</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #64748b;
      --line: #e5e7eb;
      --panel: #ffffff;
      --soft: #f8fafc;
      --wash: #eef6ff;
      --accent: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(14, 165, 233, 0.16), transparent 34rem),
        linear-gradient(135deg, #f8fafc 0%, #eef6ff 52%, #fff7ed 100%);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 36px 28px 56px; }}
    h1 {{ margin: 0; font-size: clamp(2rem, 4vw, 3.5rem); letter-spacing: -0.05em; }}
    h2 {{ margin: 0 0 18px; font-size: 1.35rem; letter-spacing: -0.02em; }}
    h3 {{ margin: 20px 0 10px; color: #334155; font-size: 1rem; }}
    section {{
      margin-top: 24px;
      padding: 24px;
      border: 1px solid rgba(226, 232, 240, 0.9);
      border-radius: 22px;
      background: rgba(255, 255, 255, 0.86);
      box-shadow: 0 18px 50px rgba(15, 23, 42, 0.08);
      backdrop-filter: blur(10px);
    }}
    .hero {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      background: linear-gradient(135deg, rgba(15, 118, 110, 0.96), rgba(15, 23, 42, 0.94));
      color: white;
    }}
    .hero .muted {{ color: rgba(255, 255, 255, 0.76); }}
    .eyebrow {{ margin: 0 0 6px; color: #99f6e4; font-size: 0.78rem; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }}
    .hero-meta {{ display: flex; flex-direction: column; gap: 8px; min-width: min(360px, 100%); }}
    .hero-meta span {{ padding: 10px 12px; border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 12px; background: rgba(255, 255, 255, 0.1); }}
    .muted {{ color: var(--muted); }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }}
    .metric-grid.five {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
    .metric-card {{ padding: 16px; border: 1px solid var(--line); border-radius: 16px; background: var(--soft); }}
    .metric-label {{ color: var(--muted); font-size: 0.78rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; }}
    .metric-value {{ margin-top: 8px; font-size: 1.45rem; font-weight: 850; letter-spacing: -0.03em; }}
    .split {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }}
    .table-wrap {{ width: 100%; overflow-x: auto; border: 1px solid var(--line); border-radius: 16px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; background: white; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #f1f5f9; color: #475569; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    tr:last-child td {{ border-bottom: 0; }}
    td {{ font-size: 0.9rem; }}
    pre {{ background: #0f172a; color: #e2e8f0; border-radius: 14px; padding: 16px; overflow: auto; }}
    details summary {{ cursor: pointer; color: var(--accent); font-weight: 800; }}
    @media (max-width: 900px) {{
      main {{ padding: 20px 14px 40px; }}
      .hero, .split {{ grid-template-columns: 1fr; display: grid; }}
      .metric-grid, .metric-grid.five {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 560px) {{
      .metric-grid, .metric-grid.five {{ grid-template-columns: 1fr; }}
      section {{ padding: 18px; border-radius: 18px; }}
    }}
  </style>
</head>
<body>
<main>
{body_html}
</main>
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
        render_llm_usage_metrics(result.get("llm_usage"))

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
            if result.get("benchmark_period"):
                st.caption(f"벤치마크 기간: `{result.get('benchmark_period')}`")
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

    benchmark_options = [CUSTOM_BENCHMARK_LABEL, *BACKTEST_BENCHMARK_PERIODS]
    benchmark_label = st.selectbox(
        "벤치마크 기간",
        options=benchmark_options,
        index=benchmark_options.index(st.session_state.get(f"{namespace}_benchmark_period", CUSTOM_BENCHMARK_LABEL))
        if st.session_state.get(f"{namespace}_benchmark_period", CUSTOM_BENCHMARK_LABEL) in benchmark_options
        else 0,
        key=f"{namespace}_benchmark_period_widget",
        help="시장 특성이 뚜렷한 기간을 빠르게 선택하거나, 직접 입력으로 원하는 기간을 지정합니다.",
    )
    st.session_state[f"{namespace}_benchmark_period"] = benchmark_label
    if benchmark_label != CUSTOM_BENCHMARK_LABEL:
        preset_start, preset_end = BACKTEST_BENCHMARK_PERIODS[benchmark_label]
        if st.session_state.get(f"{namespace}_benchmark_period_applied") != benchmark_label:
            st.session_state[f"{namespace}_start"] = preset_start
            st.session_state[f"{namespace}_end"] = preset_end
            st.session_state[f"{namespace}_benchmark_period_applied"] = benchmark_label
        st.caption(f"`{benchmark_label}` 기간: `{preset_start}` ~ `{preset_end}`")
    else:
        st.session_state[f"{namespace}_benchmark_period_applied"] = CUSTOM_BENCHMARK_LABEL

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
                benchmark_period=benchmark_label if benchmark_label != CUSTOM_BENCHMARK_LABEL else None,
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
