"""db 패키지 — MongoDB 스키마, 인덱스 정의 및 공유 연결."""

from db.connection import close_connection, get_client, get_db
from db.schemas import (AssetStateDocument, CollectionName, Holding,
                        IndicatorParam, StrategyDocument, StrategyPerformance,
                        StrategyRevision, TradeAction, TradeLogDocument,
                        ensure_indexes, make_prompt_hash)

__all__ = [
    "AssetStateDocument",
    "CollectionName",
    "Holding",
    "IndicatorParam",
    "StrategyDocument",
    "StrategyPerformance",
    "StrategyRevision",
    "TradeAction",
    "TradeLogDocument",
    "ensure_indexes",
    "make_prompt_hash",
    "close_connection",
    "get_client",
    "get_db",
]
