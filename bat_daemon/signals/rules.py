from bat_daemon.market_data.candle import ClosedCandle
from db.entity import TargetEntity
from magpie_agent.agents.meerkat_scanner.schema import TargetStatus, TriggerBasis


def is_touch_buy_signal(current_price: float, target: TargetEntity) -> bool:
    return (
        target.status == TargetStatus.WAITING_BUY
        and target.trigger_basis == TriggerBasis.TOUCH
        and target.buy_price_lower_limit <= current_price <= target.buy_price_upper_limit
    )


def should_check_close_buy(target: TargetEntity) -> bool:
    return target.status == TargetStatus.WAITING_BUY and target.trigger_basis == TriggerBasis.CLOSE


def close_buy_rejection_reason(closed_candle: ClosedCandle, target: TargetEntity) -> str | None:
    if not (target.buy_price_lower_limit <= closed_candle.close_price <= target.buy_price_upper_limit):
        return "price_out_of_range"

    if closed_candle.volume < target.min_volume_threshold:
        return "volume_too_low"

    if target.requires_bullish_close and not closed_candle.is_bullish:
        return "not_bullish"

    return None
