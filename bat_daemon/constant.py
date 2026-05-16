# DB 조회 및 WebSocket 설정 상수
from enum import StrEnum

DB_SYNC_INTERVAL_SECONDS = 60
WS_URI = "wss://api.upbit.com/websocket/v1"
WS_TICKET_NAME = "magpie_bat_daemon"
WS_CANDLE_TYPE = "candle.60m"
DB_TARGET_LIST_LIMIT = 100


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
