import datetime
import os
from typing import Annotated

from dotenv import load_dotenv
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from motor.motor_asyncio import AsyncIOMotorClient

from agents.meerkat_scanner.meerkat_schema import MonitoringTargetSchema

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client["the_nest"]
monitoring_target_collection = db["monitoring_targets"]


@tool(args_schema=MonitoringTargetSchema)
async def register_monitoring_targets_to_nest(targets: list, state: Annotated[dict, InjectedState]) -> str:
    """미어캣이 계산한 최종 타점 리스트를 DB(The-Nest)의 monitor_targets 컬렉션에 저장하여 Bat 데몬이 감시할 수 있도록 합니다."""
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
