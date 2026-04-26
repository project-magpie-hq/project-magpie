import datetime
import logging
import os
from enum import StrEnum
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agents.owl_director.schema import StrategySchema
from db.mongo import strategies_collection

logger = logging.getLogger(__name__)


def normalize_strategy_doc(strategy: dict[str, Any] | None) -> dict[str, Any] | None:
    """서로 다른 전략 저장 포맷을 후속 노드에서 재사용 가능한 형태로 정규화한다."""
    if not strategy:
        return None

    if "strategy_payload" in strategy:
        payload = strategy.get("strategy_payload") or {}
        target_market = (
            payload.get("target_market")
            or payload.get("target_coin")
            or payload.get("symbol")
            or (payload.get("trigger_spec") or {}).get("market")
        )
        target_coins = payload.get("target_coins") or ([target_market] if target_market else [])
        return {
            "target_coins": target_coins,
            "strategy_details": payload,
        }

    return {
        "target_coins": strategy.get("target_coins") or [],
        "strategy_details": strategy.get("strategy_details") or {},
    }


async def fetch_active_strategy_for_user(user_id: str) -> dict[str, Any] | None:
    strategy = await strategies_collection.find_one({"user_id": user_id, "state": "ACTIVE"})
    return normalize_strategy_doc(strategy)


@tool(args_schema=StrategySchema)
async def register_strategy_to_nest(
    target_coins: list, strategy_details: dict, state: Annotated[dict, InjectedState]
) -> str:
    """사용자가 전략을 최종 승인했을 때 호출하여, DB에 전략을 저장하거나 업데이트 합니다."""

    if os.getenv("IS_SIMULATION") == "True":
        print("✅ [시뮬레이션] 전략이 가상 메모리에 성공적으로 등록되었습니다. (DB 저장 생략)")
        return "투자 전략 등록 및 업데이트가 성공적으로 완료되었습니다."

    user_id: str | None = state.get("user_id")
    filter_query = {"user_id": user_id}

    update_query = {
        "$set": {
            "target_coins": target_coins,
            "strategy_details": strategy_details,
            "state": StrategyState.ACTIVE.value,
            "created_at": datetime.datetime.now(datetime.UTC),
        },
        # "$setOnInsert": {
        #     "created_at": datetime.datetime.now(datetime.UTC),
        # },
    }

    print("\n" + "⚙️ " * 15)
    try:
        result = await strategies_collection.update_one(filter_query, update_query, upsert=True)
    except Exception as e:
        logger.exception("전략 DB 저장 실패 (user_id: %s)", user_id)
        raise RuntimeError("전략 저장 중 DB 오류가 발생했습니다.") from e

    if result.upserted_id:
        print(f"🪹 [The Nest]: 새로운 전략이 DB에 등록되었습니다! ID: {result.upserted_id}")
    else:
        print("🪹 [The Nest]: 기존 전략이 성공적으로 업데이트(수정)되었습니다!")
    print("-" * 50)
    print("⚙️ " * 15 + "\n")

    return "투자 전략 등록 및 업데이트가 성공적으로 완료되었습니다."


@tool
async def get_my_active_strategy(state: Annotated[dict, InjectedState]) -> dict | None:
    """사용자가 본인의 전략을 열람하기 원할 때 호출하여, 활성화된 전략을 보여줍니다."""
    user_id: str | None = state.get("user_id")

    try:
        strategy = await strategies_collection.find_one({"user_id": user_id, "state": StrategyState.ACTIVE.value})
    except Exception as e:
        logger.exception("전략 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("전략 조회 중 DB 오류가 발생했습니다.") from e

    if strategy:
        strategy["_id"] = str(strategy["_id"])
        print(f"🔍 [{user_id}]님의 투자 전략을 The-Nest에서 꺼내왔습니다.")
        return strategy
    else:
        print("아직 아무것도 저장되어 있지 않습니다!")
        return None
