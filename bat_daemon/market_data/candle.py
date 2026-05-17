from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CandleTick:
    coin: str
    current_price: float
    candle_time: str | None


@dataclass(frozen=True)
class ClosedCandle:
    close_price: float
    open_price: float
    volume: float

    @property
    def is_bullish(self) -> bool:
        return self.close_price > self.open_price


def parse_tick(coin: str, tick: dict[str, Any]) -> CandleTick | None:
    current_price: float | None = tick.get("trade_price")
    if current_price is None:
        return None

    return CandleTick(
        coin=coin,
        current_price=current_price,
        candle_time=tick.get("candle_date_time_kst"),
    )


def parse_closed_candle(closed_candle: dict[str, Any]) -> ClosedCandle | None:
    close_price: float | None = closed_candle.get("trade_price")
    open_price: float | None = closed_candle.get("opening_price")
    volume: float | None = closed_candle.get("candle_acc_trade_volume")

    if close_price is None or open_price is None or volume is None:
        return None

    return ClosedCandle(close_price=close_price, open_price=open_price, volume=volume)


def is_new_candle(last_candle: dict[str, Any] | None, current_candle_time: str | None) -> bool:
    return bool(last_candle and last_candle.get("candle_date_time_kst") != current_candle_time)
