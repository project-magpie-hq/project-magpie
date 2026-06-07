import logging

from bat_daemon.constant import SignalType
from db.entity import TradeHistoryEntity
from db.mongo import get_trade_history_collection

logger = logging.getLogger(__name__)


async def register_trade_history(
    user_id: str, market: str, signal: SignalType, price: float, volume: float
) -> TradeHistoryEntity:
    """사용자의 체결 이력을 등록합니다."""

    trade_history_entity = TradeHistoryEntity.model_validate(
        {
            "user_id": user_id,
            "market": market,
            "signal": signal,
            "price": price,
            "volume": volume,
            "total_price": price * volume,
        }
    )

    print("\n" + "⚙️ " * 15)
    try:
        result = await get_trade_history_collection().insert_one(trade_history_entity.model_dump())
    except Exception as e:
        logger.exception("체결 이력 DB 저장 실패 (user_id: %s)", user_id)
        raise RuntimeError("체결 이력 저장 중 DB 오류가 발생했습니다.") from e

    print(f"🪹 [The Nest]: 새 체결 이력이 성공적으로 등록되었습니다: {result.inserted_id})")
    print("-" * 50)
    print("⚙️ " * 15 + "\n")

    return trade_history_entity


async def fetch_recent_trade_history_by_user(user_id: str, limit: int = 20) -> list[TradeHistoryEntity]:
    """사용자의 최근 체결 이력을 최신순으로 조회합니다."""

    try:
        cursor = get_trade_history_collection().find({"user_id": user_id}).sort("updated_at", -1).limit(limit)
        trades = await cursor.to_list(length=limit)
    except Exception as e:
        logger.exception("체결 이력 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("체결 이력 조회 중 DB 오류가 발생했습니다.") from e

    return [TradeHistoryEntity.model_validate(trade) for trade in trades]
