import datetime
import os
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agents.meerkat_scanner.schema import MonitoringTargetSchema
from db.mongo import monitoring_target_collection


@tool(args_schema=MonitoringTargetSchema)
async def register_monitoring_targets_to_nest(targets: list, state: Annotated[dict, InjectedState]) -> str:
    """미어캣이 계산한 최종 타점 리스트를 DB(The-Nest)의 monitor_targets 컬렉션에 저장하여 Bat 데몬이 감시할 수 있도록 합니다."""

    if os.getenv("IS_SIMULATION") == "True":
        print(targets)
        print("✅ [시뮬레이션] 타점이 가상 메모리에 성공적으로 등록되었습니다. (DB 저장 생략)")
        return "모든 타점 등록 및 업데이트가 성공적으로 완료되었습니다."

    for t in targets:
        filter_query = {"user_id": state.get("user_id"), "target_coin": t.target_coin}
        update_query = {
            "$set": t.model_dump(),
            "$setOnInsert": {
                "created_at": datetime.datetime.now(datetime.UTC),
            },
        }

        print("\n" + "⚙️ " * 15)
        result = await monitoring_target_collection.update_one(filter_query, update_query, upsert=True)
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
    cursor = await monitoring_target_collection.find({"user_id": state.get("user_id")})
    monitoring_targets = await cursor.to_list(length=100)

    if monitoring_targets:
        print(f"🔍 [{state.get('user_id')}]님의 타점을 The-Nest에서 꺼내왔습니다.")
        return monitoring_targets
    else:
        print("아직 아무것도 저장되어 있지 않습니다!")
        return None
