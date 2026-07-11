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
        "current_target_coin": target_entity.target_coin,
        "trigger_info": event_data,
    }


async def invoke_graph_for_trigger(
    trigger_graph,
    user_id: str,
    target_entity: TargetEntity,
    signal_type: SignalType,
    current_price: float,
    event_reason: str,
) -> None:
    """Bat Daemon이 매매 체결 후 Signal Trigger 그래프를 호출한다.

    trigger_graph는 build_signal_trigger_graph()로 생성된 CompiledStateGraph.
    """
    coin = target_entity.target_coin
    print(
        f"   🤝 [Daemon->Trigger]: {user_id} / {coin} / "
        f"{signal_type} 체결 완료 → Signal Trigger 그래프 호출"
    )
    if trigger_graph is None:
        raise RuntimeError("trigger_graph is not initialized")

    thread_id = build_graph_thread_id(user_id, coin, signal_type)
    inputs = build_graph_inputs(user_id, target_entity, signal_type, current_price, event_reason)
    await trigger_graph.ainvoke(inputs, config={"configurable": {"thread_id": thread_id}})
    print(f"   ✅ [Daemon->Trigger]: {coin} Signal Trigger 그래프 처리 완료")
