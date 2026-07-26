from typing import Any

import pandas as pd
import streamlit as st

from dashboard.common import pretty_json
from db.entity import TargetEntity, WalletEntity


def target_to_row(target: TargetEntity) -> dict[str, Any]:
    return {
        "coin": target.target_coin,
        "status": str(target.status),
        "trigger": str(target.trigger_basis),
        "buy_lower": target.buy_price_lower_limit,
        "buy_upper": target.buy_price_upper_limit,
        "buy_allocation_pct": target.buy_allocation_pct,
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

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
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
        "executed_volume": signal.get("executed_volume"),
        "simulated_balance": signal.get("simulated_balance"),
        "execution_error": signal.get("execution_error"),
        "wallet_user_id": signal.get("wallet_user_id"),
    }
    if target:
        row.update(
            {
                "trigger": str(target.trigger_basis),
                "buy_lower": target.buy_price_lower_limit,
                "buy_upper": target.buy_price_upper_limit,
                "buy_allocation_pct": target.buy_allocation_pct,
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
        "executed_volume": ", ".join(str(signal.get("executed_volume", "")) for signal in signals) or None,
    }
    if target_for_thresholds:
        row.update(
            {
                "trigger": str(target_for_thresholds.trigger_basis),
                "buy_lower": target_for_thresholds.buy_price_lower_limit,
                "buy_upper": target_for_thresholds.buy_price_upper_limit,
                "buy_allocation_pct": target_for_thresholds.buy_allocation_pct,
                "take_profit": target_for_thresholds.take_profit_price,
                "stop_loss": target_for_thresholds.stop_loss_price,
            }
        )
    return row


def render_wallet_snapshot(wallet: WalletEntity | None, title: str) -> None:
    st.markdown(f"##### {title}")
    if wallet is None:
        st.caption("지갑 정보가 없습니다.")
        return

    buy_count = sum(1 for trade in wallet.trade_history if getattr(trade.signal, "value", trade.signal) == "BUY")
    sell_count = sum(1 for trade in wallet.trade_history if getattr(trade.signal, "value", trade.signal) == "SELL")
    summary_cols = st.columns(4)
    summary_cols[0].metric("KRW Balance", f"{wallet.balance:,.0f}")
    summary_cols[1].metric("Assets", len([asset for asset in wallet.assets.values() if asset and asset.volume > 0]))
    summary_cols[2].metric("Buy Count", buy_count)
    summary_cols[3].metric("Sell Count", sell_count)
    st.caption(f"누적 체결 이력: {len(wallet.trade_history)}건")

    with st.expander("Wallet JSON", expanded=False):
        st.code(pretty_json(wallet.model_dump(mode="json")), language="json")


def render_signal_table(signals: list[dict[str, Any]], targets: dict[str, TargetEntity]) -> None:
    if not signals:
        st.caption("아직 조건을 만족한 BUY/SELL 신호가 없습니다.")
        return

    rows = [
        signal_context_row(signal, targets.get(str(target_coin_key)))
        for signal in signals
        if (target_coin_key := signal.get("target_coin")) is not None
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_session_stats(session_stats: Any | None, title: str) -> None:
    st.markdown(f"#### {title}")
    if session_stats is None:
        st.caption("세션 통계가 없습니다.")
        return

    cols = st.columns(4)
    cols[0].metric("Session Buy", session_stats.buy_count)
    cols[1].metric("Session Sell", session_stats.sell_count)
    cols[2].metric("Buy KRW", f"{session_stats.total_buy_krw:,.0f}")
    cols[3].metric("Sell KRW", f"{session_stats.total_sell_krw:,.0f}")


def render_tick_table(tick_rows: list[dict[str, Any]]) -> None:
    if not tick_rows:
        st.caption("수집된 tick 이벤트가 없습니다.")
        return

    st.dataframe(pd.DataFrame(tick_rows), width="stretch", hide_index=True)


def sort_rows_by_datetime(
    rows: list[dict[str, Any]],
    time_key: str,
    *,
    ascending: bool,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    frame = pd.DataFrame(rows).copy()
    if time_key in frame.columns:
        frame["_sort_time"] = pd.to_datetime(frame[time_key], errors="coerce")
        frame = frame.sort_values("_sort_time", ascending=ascending, na_position="last")
        frame = frame.drop(columns="_sort_time")
    return frame.to_dict(orient="records")
