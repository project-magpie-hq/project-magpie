# 시뮬레이션에 사용되는 시장 상황 정의
MARKET_PHASES = {
    "BULL": {
        "start": "2024-02-26 00:00:00",
        "end": "2024-03-04 00:00:00",
        "desc": "상승장 (일주일 만에 비트코인이 30% 폭등한 ETF 랠리 하이라이트)",
    },
    "BEAR": {
        "start": "2022-11-06 00:00:00",
        "end": "2022-11-13 00:00:00",
        "desc": "하락장 (FTX 파산 사태로 인한 7일간의 수직 낙하 투매장)",
    },
    "SIDEWAYS": {
        "start": "2023-08-06 00:00:00",
        "end": "2023-08-13 00:00:00",
        "desc": "횡보장 (변동성이 완전히 메말라버린 좁은 박스권 장세)",
    },
}

# 기본 전략 폴백 설정
DEFAULT_STRATEGY = {
    "target_coins": ["KRW-BTC"],
    "strategy_details": {
        "trend": "횡보장",
        "risk_level": "보수적",
        "condition": "1시간 ATR 기반 하단 매수, 짧은 익절",
    },
}

# 시스템 이벤트 문구
TRIGGER_PHRASE = "[SYSTEM_EVENT: TRIGGER_MONITORING_UPDATE]"
