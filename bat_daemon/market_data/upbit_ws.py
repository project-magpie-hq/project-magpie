import json
from typing import Any

import websockets

from bat_daemon.constant import WS_CANDLE_TYPE, WS_TICKET_NAME, WS_URI


def connect_upbit_ws() -> Any:
    return websockets.connect(WS_URI, ping_interval=60, ping_timeout=30)


async def subscribe_candles(websocket: Any, user_id: str, coins: set[str]) -> None:
    await websocket.send(json.dumps(_build_subscribe_payload(user_id, coins)))


async def receive_candle_tick(websocket: Any) -> tuple[str | None, dict[str, Any]]:
    data = await websocket.recv()
    tick: dict[str, Any] = json.loads(data)
    return tick.get("code"), tick


def _build_subscribe_payload(user_id: str, coins: set[str]) -> list[dict[str, Any]]:
    return [
        {"ticket": f"{WS_TICKET_NAME}-{user_id}"},
        {"type": WS_CANDLE_TYPE, "codes": list(coins)},
    ]
