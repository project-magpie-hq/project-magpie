from pydantic import BaseModel, Field

from bat_daemon.constant import SignalType
from db.entity import TradeHistoryEntry


class TradeSessionStats(BaseModel):
    total_buy_krw: float = Field(default=0.0, ge=0.0, description="세션 내 누적 매수 금액")
    total_sell_krw: float = Field(default=0.0, ge=0.0, description="세션 내 누적 매도 금액")
    buy_count: int = Field(default=0, ge=0, description="세션 내 매수 횟수")
    sell_count: int = Field(default=0, ge=0, description="세션 내 매도 횟수")
    trade_history: list[TradeHistoryEntry] = Field(default_factory=list, description="세션 내 체결 이력")


def summarize_session_trades(trades: list[TradeHistoryEntry]) -> TradeSessionStats:
    summary = TradeSessionStats(trade_history=list(trades))

    for trade in trades:
        if trade.signal == SignalType.BUY:
            summary.total_buy_krw += trade.total_price
            summary.buy_count += 1
        else:
            summary.total_sell_krw += trade.total_price
            summary.sell_count += 1

    return summary


def build_session_stats_from_signal_history(signal_history: list[dict]) -> TradeSessionStats:
    trades: list[TradeHistoryEntry] = []

    for signal in signal_history:
        volume = signal.get("executed_volume")
        price = signal.get("price")
        signal_type = signal.get("signal_type")
        if volume in (None, "", "-") or price is None or signal.get("execution_error"):
            continue

        assert isinstance(signal_type, str), f"signal_type must be str, got {type(signal_type)}"

        try:
            parsed_volume = float(volume)
            parsed_price = float(price)
        except (TypeError, ValueError) as exc:
            raise AssertionError(f"invalid trade payload: price={price}, volume={volume}") from exc

        trades.append(
            TradeHistoryEntry(
                market=signal["target_coin"],
                signal=SignalType(signal_type),
                price=parsed_price,
                volume=parsed_volume,
                total_price=parsed_price * parsed_volume,
            )
        )

    return summarize_session_trades(trades)
