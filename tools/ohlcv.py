"""
OHLCV 데이터 로드 도구 — 업비트 Open API (pyupbit).

pyupbit.get_ohlcv() 는 동기 함수이므로 asyncio.to_thread 로 래핑한다.

지원 interval:
  일봉  : "day"
  주봉  : "week"
  월봉  : "month"
  분봉  : "minute1", "minute3", "minute5", "minute10",
           "minute15", "minute30", "minute60", "minute240"

업비트 심볼 형식: "KRW-BTC", "KRW-ETH", ...
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import pyupbit
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

OhlcvInterval = Literal[
    "day", "week", "month",
    "minute1", "minute3", "minute5", "minute10",
    "minute15", "minute30", "minute60", "minute240",
]


@tool
async def get_ohlcv_tool(
    symbol: str,
    interval: str = "day",
    count: int = 200,
) -> list[dict]:
    """업비트 Open API를 통해 OHLCV(시가·고가·저가·종가·거래량) 캔들 데이터를 가져옵니다.

    Args:
        symbol:   업비트 마켓 코드. 예: 'KRW-BTC', 'KRW-ETH'.
        interval: 캔들 단위. 'day'(일봉) / 'minute60'(1시간봉) 등.
                  기본값: 'day'.
        count:    가져올 캔들 개수 (최대 200). 기본값: 200.

    Returns:
        각 캔들을 dict로 담은 리스트.
        키: timestamp(ISO), open, high, low, close, volume
    """
    logger.info("[OHLCV] %s %s ×%d 요청", symbol, interval, count)

    df = await asyncio.to_thread(
        pyupbit.get_ohlcv,
        symbol,
        interval=interval,
        count=count,
    )

    if df is None or df.empty:
        logger.warning("[OHLCV] 데이터 없음: %s %s", symbol, interval)
        return []

    df = df.sort_index()
    records = []
    for ts, row in df.iterrows():
        records.append({
            "timestamp": ts.isoformat(),
            "open":   float(row["open"]),
            "high":   float(row["high"]),
            "low":    float(row["low"]),
            "close":  float(row["close"]),
            "volume": float(row["volume"]),
        })

    logger.info("[OHLCV] %d 개 캔들 반환", len(records))
    return records
