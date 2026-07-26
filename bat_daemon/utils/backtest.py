from datetime import UTC, datetime
from typing import Any, Callable

import pandas as pd

from magpie_agent.tools.strategy import fetch_strategy_by_user

BacktestProgressCallback = Callable[[dict[str, Any]], None]
BACKTEST_CANDLE_INTERVAL = "minute1"
BACKTEST_REPLAY_MODES = ("close_only", "ohlc_path", "open_only")
DEFAULT_BACKTEST_REPLAY_MODE = "close_only"
BACKTEST_CLOSE_WINDOW_MINUTES = 60


def backtest_warmup_start(value: str, *, window_minutes: int = BACKTEST_CLOSE_WINDOW_MINUTES) -> str:
    return (pd.Timestamp(value) - pd.Timedelta(minutes=max(0, window_minutes - 1))).strftime("%Y-%m-%d %H:%M:%S")


def emit_backtest_event(
    progress_callback: BacktestProgressCallback | None,
    event_type: str,
    message: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return

    progress_callback(
        {
            "event_type": event_type,
            "message": message,
            "recorded_at": datetime.now(UTC).isoformat(),
            **payload,
        }
    )


def format_candle_time(index: pd.Timestamp) -> str:
    return index.strftime("%Y-%m-%dT%H:%M:%S")


def normalize_backtest_time(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%S")


def candle_path(candle: pd.Series) -> list[tuple[str, float]]:
    open_price = float(candle["open"])
    high_price = float(candle["high"])
    low_price = float(candle["low"])
    close_price = float(candle["close"])

    if close_price >= open_price:
        path = [("open", open_price), ("low", low_price), ("high", high_price), ("close", close_price)]
    else:
        path = [("open", open_price), ("high", high_price), ("low", low_price), ("close", close_price)]

    deduped_path: list[tuple[str, float]] = []
    for point_name, price in path:
        if not deduped_path or deduped_path[-1][1] != price:
            deduped_path.append((point_name, price))
    return deduped_path


def candle_replay_points(candle: pd.Series, replay_mode: str) -> list[tuple[str, float]]:
    if replay_mode == "close_only":
        return [("close", float(candle["close"]))]
    if replay_mode == "open_only":
        return [("open", float(candle["open"]))]
    if replay_mode == "ohlc_path":
        return candle_path(candle)
    raise ValueError(f"지원하지 않는 replay_mode 입니다: {replay_mode}")


def to_upbit_tick(coin: str, candle_time: pd.Timestamp, candle: pd.Series, trade_price: float) -> dict[str, Any]:
    return {
        "code": coin,
        "candle_date_time_kst": format_candle_time(candle_time),
        "opening_price": float(candle["open"]),
        "high_price": float(candle["high"]),
        "low_price": float(candle["low"]),
        "trade_price": trade_price,
        "candle_acc_trade_volume": float(candle["volume"]),
        "candle_acc_trade_price": float(candle.get("value", 0.0)),
        "candle_window_complete": bool(candle.get("window_complete", True)),
        "candle_window_minutes": int(candle.get("window_minutes", BACKTEST_CLOSE_WINDOW_MINUTES)),
    }


def build_rolling_window_candle(
    df: pd.DataFrame,
    candle_time: pd.Timestamp,
    *,
    window_minutes: int = BACKTEST_CLOSE_WINDOW_MINUTES,
) -> pd.Series:
    window_df = df.loc[:candle_time].tail(window_minutes)
    if window_df.empty:
        raise ValueError(f"rolling window candle을 만들 수 없습니다: {candle_time}")

    return pd.Series(
        {
            "open": float(window_df.iloc[0]["open"]),
            "high": float(window_df["high"].max()),
            "low": float(window_df["low"].min()),
            "close": float(window_df.iloc[-1]["close"]),
            "volume": float(window_df["volume"].sum()),
            "value": float(window_df["value"].sum()) if "value" in window_df.columns else 0.0,
            "window_complete": len(window_df) >= window_minutes,
            "window_minutes": window_minutes,
        }
    )


async def load_backtest_universe(backtest_id: str) -> set[str]:
    strategy = await fetch_strategy_by_user(backtest_id)
    if strategy is None:
        return set()
    return set(strategy.get("target_coins") or [])


def build_backtest_tick_row(
    coin: str,
    tick: dict[str, Any],
    target_before: Any,
    target_after: Any,
    signals: list[dict[str, Any]],
    source: str = "backtest",
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


def build_backtest_result(initial_targets: dict[str, Any], final_targets: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "initial_targets": initial_targets,
        "final_targets": final_targets,
        "tick_rows": [],
        "signals": [],
        "session_stats": None,
        "processed_ticks": 0,
        "error": error,
        "wallet": None,
        "wallet_user_id": None,
        "strategy_user_id": None,
        "backtest_id": None,
        "selected_target_coins": None,
        "generated_targets": None,
        "loaded_candles": {},
    }


def limit_tick_rows_for_report(tick_rows: list[dict[str, Any]], max_tick_rows: int | None) -> list[dict[str, Any]]:
    if max_tick_rows is None or len(tick_rows) <= max_tick_rows:
        return tick_rows

    signal_indexes = [idx for idx, row in enumerate(tick_rows) if row.get("signal")]
    kept_indexes: set[int] = set(signal_indexes)
    kept_indexes.add(0)
    kept_indexes.add(len(tick_rows) - 1)

    remaining_slots = max_tick_rows - len(kept_indexes)
    if remaining_slots <= 0:
        selected_indexes = sorted(kept_indexes)[:max_tick_rows]
        return [tick_rows[idx] for idx in selected_indexes]

    step = max(1, len(tick_rows) // remaining_slots)
    sampled_indexes = range(0, len(tick_rows), step)
    for idx in sampled_indexes:
        kept_indexes.add(idx)
        if len(kept_indexes) >= max_tick_rows:
            break

    selected_indexes = sorted(kept_indexes)
    if len(selected_indexes) > max_tick_rows:
        selected_indexes = selected_indexes[:max_tick_rows]
    return [tick_rows[idx] for idx in selected_indexes]
