import datetime
import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from db.entity import TargetEntity
from db.mongo import get_monitoring_targets_collection
from magpie_agent.agents.meerkat_scanner.schema import MonitoringTargets, TargetSchema

logger = logging.getLogger(__name__)


@tool(args_schema=MonitoringTargets)
async def register_monitoring_targets_to_nest(
    targets: list[TargetSchema], state: Annotated[dict, InjectedState]
) -> str:
    """미어캣이 계산한 최종 타점 리스트를 DB(The-Nest)의 monitor_targets 컬렉션에 저장하여 Bat 데몬이 감시할 수 있도록 합니다."""

    user_id: str = state["user_id"]

    target_details = []
    for target in targets:
        target_entity = TargetEntity.model_validate({"user_id": user_id, **target.model_dump()})
        filter_query = {
            "user_id": target_entity.user_id,
            "target_coin": target_entity.target_coin,
        }

        update_query = {
            "$set": target_entity.model_dump(),
            "$setOnInsert": {
                "created_at": datetime.datetime.now(datetime.UTC),
            },
        }

        print("\n" + "⚙️ " * 15)
        try:
            result = await get_monitoring_targets_collection().update_one(filter_query, update_query, upsert=True)
        except Exception as e:
            logger.exception(
                "타점 DB 저장 실패 (user_id: %s, coin: %s)",
                user_id,
                target_entity.target_coin,
            )
            raise RuntimeError(f"{target_entity.target_coin} 타점 저장 중 DB 오류가 발생했습니다.") from e

        if result.upserted_id:
            print(f"🪹 [The Nest]: 새로운 타점이 DB에 등록되었습니다! ID: {result.upserted_id}")
        else:
            print("🪹 [The Nest]: 기존 타점이 성공적으로 업데이트되었습니다!")

        # 상세 로깅
        coin = target_entity.target_coin
        target_details.append(
            f"• {coin}: 매수 {target_entity.buy_price_lower_limit:,.0f}~{target_entity.buy_price_upper_limit:,.0f}원 "
            f"| 익절 {target_entity.take_profit_price:,.0f}원 "
            f"| 손절 {target_entity.stop_loss_price:,.0f}원 "
            f"| 할당 {target_entity.buy_allocation_pct*100:.0f}%"
            f"({target_entity.trigger_basis.value})"
        )
        print(f"   📊 [{coin}] 타점 상세: "
              f"매수구간 {target_entity.buy_price_lower_limit:,.0f}~{target_entity.buy_price_upper_limit:,.0f} | "
              f"익절 {target_entity.take_profit_price:,.0f} | "
              f"손절 {target_entity.stop_loss_price:,.0f} | "
              f"할당 {target_entity.buy_allocation_pct*100:.0f}% | "
              f"기준 {target_entity.trigger_basis.value}")
        print(f"   📝 [{coin}] 근거: {target_entity.reason}")
        print("-" * 50)
        print("⚙️ " * 15 + "\n")

    return "모든 타점 등록 및 업데이트가 성공적으로 완료되었습니다."


async def fetch_monitoring_targets_by_user(user_id: str) -> list[dict] | None:
    try:
        cursor = get_monitoring_targets_collection().find({"user_id": user_id})
        monitoring_targets = await cursor.to_list(length=100)
    except Exception as e:
        logger.exception("타점 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("타점 조회 중 DB 오류가 발생했습니다.") from e

    return monitoring_targets if monitoring_targets else None


async def clear_monitoring_targets_by_user(user_id: str) -> int:
    try:
        result = await get_monitoring_targets_collection().delete_many({"user_id": user_id})
    except Exception as e:
        logger.exception("타점 DB 삭제 실패 (user_id: %s)", user_id)
        raise RuntimeError("타점 삭제 중 DB 오류가 발생했습니다.") from e

    return result.deleted_count


@tool
async def get_my_all_monitoring_targets(
    state: Annotated[dict, InjectedState],
) -> list | None:
    """사용자의 타점을 열람하기 원할 때 호출하여, 사용자의 모든 타점을 보여줍니다."""
    user_id: str = state["user_id"]
    monitoring_targets = await fetch_monitoring_targets_by_user(user_id)

    if monitoring_targets:
        print(f"🔍 [{user_id}]님의 타점을 The-Nest에서 꺼내왔습니다.")
        return monitoring_targets
    else:
        print("아직 아무것도 저장되어 있지 않습니다!")
        return None
