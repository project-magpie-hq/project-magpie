import datetime
import logging
import os
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agents.meerkat_scanner.schema import MonitoringTargets, TargetSchema
from db.mongo import monitoring_target_collection

logger = logging.getLogger(__name__)


@tool(args_schema=MonitoringTargets)
async def register_monitoring_targets_to_nest(
    targets: list[dict[str, Any]], state: Annotated[dict, InjectedState]
) -> str:
    """미어캣이 계산한 최종 타점 리스트를 DB(The-Nest)의 monitor_targets 컬렉션에 저장하여 Bat 데몬이 감시할 수 있도록 합니다."""

    if os.getenv("IS_SIMULATION") == "True":
        print(targets)
        print("✅ [시뮬레이션] 타점이 가상 메모리에 성공적으로 등록되었습니다. (DB 저장 생략)")
        return "모든 타점 등록 및 업데이트가 성공적으로 완료되었습니다."

    user_id: str | None = state.get("user_id")

    for target in targets:
        target_schema = TargetSchema.model_validate(target)
        filter_query = {"user_id": user_id, "target_coin": target_schema.target_coin}
        dumped_schema = target_schema.model_dump()
        dumped_schema["created_at"] = datetime.datetime.now(datetime.UTC)
        update_query = {
            "$set": dumped_schema,
            # "$setOnInsert": {
            #     "created_at": datetime.datetime.now(datetime.UTC),
            # },
        }

        print("\n" + "⚙️ " * 15)
        try:
            result = await monitoring_target_collection.update_one(filter_query, update_query, upsert=True)
        except Exception as e:
            logger.exception("타점 DB 저장 실패 (user_id: %s, coin: %s)", user_id, target_schema.target_coin)
            raise RuntimeError(f"{target_schema.target_coin} 타점 저장 중 DB 오류가 발생했습니다.") from e

        if result.upserted_id:
            print(f"🪹 [The Nest]: 새로운 타점이 DB에 등록되었습니다! ID: {result.upserted_id}")
        else:
            print("🪹 [The Nest]: 기존 타점이 성공적으로 업데이트되었습니다!")
        print("-" * 50)
        print("⚙️ " * 15 + "\n")

    return "모든 타점 등록 및 업데이트가 성공적으로 완료되었습니다."


@tool
async def get_my_all_monitoring_targets(state: Annotated[dict, InjectedState]) -> list | None:
    """사용자의 타점을 열람하기 원할 때 호출하여, 사용자의 모든 타점을 보여줍니다."""
    user_id: str | None = state.get("user_id")

    try:
        cursor = monitoring_target_collection.find({"user_id": user_id})
        monitoring_targets = await cursor.to_list(length=100)
    except Exception as e:
        logger.exception("타점 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("타점 조회 중 DB 오류가 발생했습니다.") from e

    if monitoring_targets:
        print(f"🔍 [{user_id}]님의 타점을 The-Nest에서 꺼내왔습니다.")
        return monitoring_targets
    else:
        print("아직 아무것도 저장되어 있지 않습니다!")
        return None
