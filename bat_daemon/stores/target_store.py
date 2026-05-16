from bat_daemon.constant import DB_TARGET_LIST_LIMIT
from db.entity import TargetEntity
from db.mongo import monitoring_targets_collection
from magpie_agent.agents.meerkat_scanner.schema import TargetStatus


async def fetch_target_map(user_id: str) -> dict[str, TargetEntity]:
    cursor = monitoring_targets_collection.find({"user_id": {"$in": [user_id]}})
    targets = await cursor.to_list(length=DB_TARGET_LIST_LIMIT)

    return {
        target_entity.target_coin: target_entity
        for target_entity in (TargetEntity.model_validate(target) for target in targets)
    }


async def update_target_status(user_id: str, target_coin: str, new_status: TargetStatus) -> None:
    await monitoring_targets_collection.update_one(
        {"user_id": user_id, "target_coin": target_coin},
        {"$set": {"status": new_status}},
    )
