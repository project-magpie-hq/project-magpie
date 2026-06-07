import datetime
import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from db.entity import StrategyEntity
from db.mongo import get_strategies_collection
from magpie_agent.agents.hawk_picker.schema import UpdateTargetCoinsInput
from magpie_agent.agents.owl_director.schema import StrategySchema
from magpie_agent.tools.telegram import send_telegram_message

logger = logging.getLogger(__name__)


@tool(args_schema=StrategySchema)
async def register_strategy_to_nest(
    target_coins: list, strategy_details: dict, state: Annotated[dict, InjectedState]
) -> str:
    """사용자가 전략을 최종 승인했을 때 호출하여, DB에 전략을 저장하거나 업데이트 합니다."""

    if state.get("current_sim_time"):
        print("✅ [시뮬레이션] 전략이 가상 메모리에 성공적으로 등록되었습니다. (DB 저장 생략)")
        return "투자 전략 등록 및 업데이트가 성공적으로 완료되었습니다."

    user_id: str = state["user_id"]
    strategy_entity = StrategyEntity.model_validate(
        {"user_id": user_id, "target_coins": target_coins, "strategy_details": strategy_details}
    )
    filter_query = {"user_id": strategy_entity.user_id}

    update_query = {
        "$set": strategy_entity.model_dump(),
        "$setOnInsert": {
            "created_at": datetime.datetime.now(datetime.UTC),
        },
    }

    print("\n" + "⚙️ " * 15)
    try:
        result = await get_strategies_collection().update_one(filter_query, update_query, upsert=True)
    except Exception as e:
        logger.exception("전략 DB 저장 실패 (user_id: %s)", user_id)
        raise RuntimeError("전략 저장 중 DB 오류가 발생했습니다.") from e

    if result.upserted_id:
        print(f"🪹 [The Nest]: 새로운 전략이 DB에 등록되었습니다! ID: {result.upserted_id}")
        await send_telegram_message(
            chat_id=user_id,
            text=(
                "🦉 [전략 등록]\n"
                f"새로운 투자 전략이 등록되었습니다.\n"
                f"• 대상 코인: {', '.join(strategy_entity.target_coins) if strategy_entity.target_coins else '미정'}\n"
                f"• 전략 개요: Hawk Picker가 종목을 선정하고 Meerkat이 타점을 계산합니다."
            ),
        )
    else:
        print("🪹 [The Nest]: 기존 전략이 성공적으로 업데이트(수정)되었습니다!")
        await send_telegram_message(
            chat_id=user_id,
            text=(
                "🦉 [전략 변경]\n"
                f"기존 전략이 업데이트되었습니다.\n"
                f"• 대상 코인: {', '.join(strategy_entity.target_coins) if strategy_entity.target_coins else '미정'}\n"
                f"• 변경된 전략 세부사항이 DB에 반영되었습니다.\n"
                f"• Hawk Picker와 Meerkat Scanner가 새로운 전략으로 분석을 시작합니다."
            ),
        )
    print("-" * 50)
    print("⚙️ " * 15 + "\n")

    return "투자 전략 등록 및 업데이트가 성공적으로 완료되었습니다."


async def fetch_strategy_by_user(user_id: str) -> dict | None:
    try:
        strategy = await get_strategies_collection().find_one({"user_id": user_id})
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


@tool
async def get_my_active_strategy(state: Annotated[dict, InjectedState]) -> dict | None:
    """사용자가 본인의 전략을 열람하기 원할 때 호출하여, 활성화된 전략을 보여줍니다."""
    strategy = await fetch_strategy_by_user(state["user_id"])
    return strategy


@tool(args_schema=UpdateTargetCoinsInput)
async def update_strategy_target_coins(
    target_coins: list[str],
    state: Annotated[dict, InjectedState],
) -> str:
    """
    호크가 최종 선정한 타겟 코인 리스트를 전략에 업데이트합니다.
    Hawk Picker가 차트 분석 후 최종 선정한 코인들을 전략에 반영할 때 호출합니다.
    """
    if state.get("current_sim_time"):
        print("✅ [시뮬레이션] 타겟 코인이 가상 메모리에 성공적으로 업데이트되었습니다. (DB 저장 생략)")
        return "타겟 코인 업데이트가 성공적으로 완료되었습니다."

    user_id: str = state["user_id"]
    now = datetime.datetime.now(datetime.UTC)

    filter_query = {"user_id": user_id}
    update_query = {
        "$set": {
            "target_coins": target_coins,
            "updated_at": now,
        }
    }

    print("\n" + "⚙️ " * 15)
    try:
        result = await get_strategies_collection().update_one(filter_query, update_query)
    except Exception as e:
        logger.exception("타겟 코인 업데이트 실패 (user_id: %s)", user_id)
        raise RuntimeError("타겟 코인 업데이트 중 DB 오류가 발생했습니다.") from e

    if result.modified_count > 0:
        print(f"🪹 [The Nest]: 타겟 코인이 성공적으로 업데이트되었습니다! -> {target_coins}")
        await send_telegram_message(
            chat_id=user_id,
            text=(
                "🦅 [종목 변경]\n"
                f"Hawk Picker가 최종 종목을 선정하여 전략에 반영했습니다.\n"
                f"• 선정 종목: {', '.join(target_coins)}\n"
                f"• Meerkat Scanner가 위 종목들의 타점을 계산 중입니다."
            ),
        )
    else:
        print("⚠️ [The Nest]: 업데이트할 전략이 없습니다. (혹시 전략이 등록되지 않았나요?)")
    print("-" * 50)
    print("⚙️ " * 15 + "\n")

    return f"타겟 코인이 {target_coins}(으)로 성공적으로 업데이트되었습니다."
