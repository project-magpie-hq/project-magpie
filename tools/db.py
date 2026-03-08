"""
백테스트용 MongoDB 도구 모음 — Meerkat Scanner가 호출한다.

tools:
  - find_existing_strategy   : (prompt_hash, symbol) 기존 전략 조회
  - save_backtest_strategy   : 전략 신규 저장 또는 수정 이력 추가
  - update_strategy_performance : 백테스트 완료 후 KPI 기록
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from dotenv import load_dotenv
from langchain_core.tools import tool

from db.connection import get_db
from db.schemas import (CollectionName, IndicatorParam, StrategyDocument,
                        StrategyPerformance, StrategyRevision,
                        make_prompt_hash)

load_dotenv()
logger = logging.getLogger(__name__)

_db = get_db()


# ---------------------------------------------------------------------------
# 1. 기존 전략 조회
# ---------------------------------------------------------------------------

@tool
async def find_existing_strategy(prompt: str, symbol: str) -> dict | None:
    """MongoDB에서 동일한 요청(prompt + symbol)으로 생성된 전략이 있는지 확인합니다.

    전략이 존재하면 전략 도큐먼트 전체를 반환합니다.
    없으면 None을 반환합니다.

    Args:
        prompt: 사용자 원본 요청 문자열.
        symbol: 대상 종목 심볼. 예: 'KRW-BTC'.
    """
    ph = make_prompt_hash(prompt, symbol)
    doc = await _db[CollectionName.STRATEGIES].find_one({"prompt_hash": ph, "symbol": symbol.upper()})
    if doc:
        doc["_id"] = str(doc["_id"])
        logger.info("[DB] 기존 전략 발견 — symbol=%s, id=%s", symbol, doc["_id"])
        return doc
    logger.info("[DB] 기존 전략 없음 — symbol=%s", symbol)
    return None


# ---------------------------------------------------------------------------
# 2. 전략 저장 / 수정 이력 추가
# ---------------------------------------------------------------------------

@tool
async def save_backtest_strategy(
    prompt: str,
    symbol: str,
    style: str,
    indicators: list[dict],
    revision_reason: str | None = None,
) -> dict:
    """확정된 전략을 MongoDB strategies 컬렉션에 저장하거나, 기존 전략을 수정합니다.

    - 기존 전략이 없으면 신규 저장합니다.
    - 기존 전략이 있고 revision_reason이 전달되면 수정 이력(revision_history)을 추가합니다.

    Args:
        prompt:          사용자 원본 요청 문자열.
        symbol:          종목 심볼. 예: 'KRW-BTC'.
        style:           매매 스타일. 예: 'aggressive', 'stable', 'balanced'.
        indicators:      지표 구성 리스트. 각 항목: {name, params, weight}.
        revision_reason: 전략 수정 사유 (기존 전략 수정 시 필수). 신규 저장이면 None.

    Returns:
        저장된 전략의 _id와 prompt_hash를 담은 dict.
    """
    ph = make_prompt_hash(prompt, symbol)
    sym = symbol.upper()
    now = datetime.now(UTC)

    parsed_indicators = [
        IndicatorParam(
            name=ind["name"],
            params=ind.get("params", {}),
            weight=ind.get("weight", 1.0),
        )
        for ind in indicators
    ]

    existing = await _db[CollectionName.STRATEGIES].find_one({"prompt_hash": ph, "symbol": sym})

    if existing is None:
        # 신규 저장
        doc = StrategyDocument(
            prompt_hash=ph,
            symbol=sym,
            style=style,
            indicators=parsed_indicators,
        )
        payload = doc.model_dump(by_alias=True)
        await _db[CollectionName.STRATEGIES].insert_one(payload)
        strat_id = doc.id
        logger.info("[DB] 전략 신규 저장 — id=%s", strat_id)
    else:
        strat_id = str(existing["_id"])

        update: dict = {
            "$set": {
                "style": style,
                "indicators": [ind.model_dump() for ind in parsed_indicators],
                "updated_at": now,
            }
        }

        if revision_reason:
            revision = StrategyRevision(
                revised_at=now,
                reason=revision_reason,
                previous_indicators=[
                    IndicatorParam(**i) for i in existing.get("indicators", [])
                ],
                new_indicators=parsed_indicators,
                previous_performance=(
                    StrategyPerformance(**existing["performance"])
                    if existing.get("performance")
                    else None
                ),
            )
            update["$push"] = {"revision_history": revision.model_dump()}

        await _db[CollectionName.STRATEGIES].update_one({"_id": existing["_id"]}, update)
        logger.info("[DB] 전략 수정 완료 — id=%s, reason=%s", strat_id, revision_reason)

    return {"strategy_id": strat_id, "prompt_hash": ph}


# ---------------------------------------------------------------------------
# 3. KPI 업데이트
# ---------------------------------------------------------------------------

@tool
async def update_strategy_performance(
    strategy_id: str,
    profit_rate: float,
    win_rate: float,
    sharpe_ratio: float,
    max_drawdown: float,
    total_trades: int,
) -> str:
    """백테스트 완료 후 전략의 성과 지표(KPI)를 MongoDB에 기록합니다.

    Args:
        strategy_id:   업데이트할 전략의 _id.
        profit_rate:   수익률 (%).
        win_rate:      승률 (%).
        sharpe_ratio:  샤프 지수.
        max_drawdown:  최대 낙폭 MDD (%).
        total_trades:  총 거래 횟수.
    """
    perf = StrategyPerformance(
        profit_rate=profit_rate,
        win_rate=win_rate,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        total_trades=total_trades,
        evaluated_at=datetime.now(UTC),
    )
    await _db[CollectionName.STRATEGIES].update_one(
        {"_id": strategy_id},
        {
            "$set": {
                "performance": perf.model_dump(),
                "updated_at": datetime.now(UTC),
            }
        },
    )
    logger.info("[DB] KPI 업데이트 완료 — strategy_id=%s, profit=%.2f%%", strategy_id, profit_rate)
    return f"성과 지표가 전략 {strategy_id}에 업데이트되었습니다."
