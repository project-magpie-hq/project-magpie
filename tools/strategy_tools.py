import datetime
import os

from dotenv import load_dotenv
from langchain_core.tools import tool
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client["the_nest"]
strategies_collection = db["strategies"]


@tool
async def register_strategy_to_nest(user_id: str, strategy_json: dict) -> str:
    """사용자가 전략을 최종 승인했을 때 호출하여, DB에 전략을 저장하거나 업데이트 합니다."""
    filter_query = {"user_id": user_id}

    update_query = {
        "$set": {
            "strategy": strategy_json,
            "state": "ACTIVE",
            "update_at": datetime.datetime.now(datetime.UTC),
        },
        "$setOnInsert": {
            "created_at": datetime.datetime.now(datetime.UTC),
        },
    }

    print("\n" + "⚙️" * 25)
    result = await strategies_collection.update_one(filter_query, update_query, upsert=True)
    if result.upserted_id:
        print(f"🪹 [The Nest]: 새로운 전략이 DB에 등록되었습니다! ID: {result.upserted_id}")
    else:
        print("🪹 [The Nest]: 기존 전략이 성공적으로 업데이트(수정)되었습니다!")
    print("-" * 50)
    print("⚙️" * 25 + "\n")

    return "투자 전략 등록 및 업데이트가 성공적으로 완료되었습니다."


@tool
async def get_my_active_strategy(user_id: str) -> dict | None:
    """사용자가 본인의 전략을 열람하기 원할 때 호출하여, 활성화된 전략을 보여줍니다."""
    strategy = await strategies_collection.find_one({"user_id": user_id, "state": "ACTIVE"})

    if strategy:
        strategy["_id"] = str(strategy["_id"])
        print(f"🔍 [{user_id}]님의 투자 전략을 The-Nest에서 꺼내왔습니다.")
        return strategy
    else:
        print("아직 아무것도 저장되어 있지 않습니다!")
        return None
