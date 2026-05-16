import datetime
import json

from bat_daemon.constant import SignalType
from db.entity import TargetEntity


def build_graph_thread_id(user_id: str, target_coin: str, signal_type: SignalType) -> str:
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
    return f"daemon:{user_id}:{target_coin}:{signal_type}:{timestamp}"


def build_graph_inputs(
    user_id: str,
    target_entity: TargetEntity,
    signal_type: SignalType,
    current_price: float,
    event_reason: str,
) -> dict:
    event_data = {
        "target_coin": target_entity.target_coin,
        "signal_type": signal_type.value if hasattr(signal_type, "value") else signal_type,
        "current_price": current_price,
        "event_reason": event_reason,
    }

    user_message = f"""[SYSTEM_ALERT: TARGET_REACHED]\n{json.dumps(event_data, ensure_ascii=False, indent=2)}"""

    return {
        "user_id": user_id,
        "messages": [user_message],
        "from_daemon": True,
    }


async def invoke_graph_for_trigger(
    magpie_graph,
    user_id: str,
    target_entity: TargetEntity,
    signal_type: SignalType,
    current_price: float,
    event_reason: str,
) -> None:
    print(
        f"   🤝 [Daemon->Graph]: {user_id} / {target_entity.target_coin} / "
        f"{signal_type} 이벤트를 Owl 그래프로 전달합니다."
    )
    if magpie_graph is None:
        raise RuntimeError("magpie_graph is not initialized")

    thread_id = build_graph_thread_id(user_id, target_entity.target_coin, signal_type)
    inputs = build_graph_inputs(user_id, target_entity, signal_type, current_price, event_reason)
    await magpie_graph.ainvoke(inputs, config={"configurable": {"thread_id": thread_id}})
