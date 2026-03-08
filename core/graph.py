"""
공유 Meerkat 그래프 빌더 및 전략 로드 유틸리티.

BacktestEngine과 LiveEngine 양쪽에서 동일하게 사용한다.
"""

from __future__ import annotations

import asyncio
import logging

import pyupbit
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents.meerkat_scanner.scanner import meerkat_scanner_node
from db.connection import get_db
from db.schemas import CollectionName
from tools.db import find_existing_strategy, save_backtest_strategy
from tools.ohlcv import get_ohlcv_tool

logger = logging.getLogger(__name__)


def build_meerkat_graph():
    """Meerkat LangGraph를 생성한다 (전략 설계 전용 단발 그래프).

    BacktestEngine / LiveEngine 모두 이 함수를 통해 그래프를 만든다.
    """
    from state.agent import AgentState

    tools = [get_ohlcv_tool, find_existing_strategy, save_backtest_strategy]
    tool_node = ToolNode(tools)

    workflow = StateGraph(AgentState)
    workflow.add_node("meerkat_scanner", meerkat_scanner_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "meerkat_scanner")
    workflow.add_conditional_edges("meerkat_scanner", tools_condition)
    workflow.add_edge("tools", "meerkat_scanner")

    return workflow.compile()


async def run_meerkat(
    user_prompt: str,
    symbol: str,
    style: str,
    session_id: str,
) -> tuple[str, dict]:
    """Meerkat 그래프를 실행하여 (strategy_id, strategy_dict)를 반환한다.

    BacktestEngine과 LiveEngine에서 중복되던 _run_meerkat 로직을 통합한 함수.

    Args:
        user_prompt: 사용자 원본 요청.
        symbol: 업비트 마켓 코드. 예: 'KRW-BTC'.
        style: 매매 스타일. 예: 'aggressive', 'stable', 'balanced'.
        session_id: 실행 세션 ID.

    Returns:
        (strategy_id, strategy_dict) 튜플.

    Raises:
        RuntimeError: 전략을 확보하지 못한 경우.
    """
    from state.agent import AgentState

    graph = build_meerkat_graph()
    initial_state: AgentState = {
        "messages": [("user", user_prompt)],
        "session_id": session_id,
        "user_prompt": user_prompt,
        "symbol": symbol,
        "style": style,
        "strategy_id": None,
        "strategy": None,
        "current_ohlcv_window": None,
        "current_timestamp": None,
    }

    cfg = {"configurable": {"thread_id": session_id}}
    final_state = await graph.ainvoke(initial_state, config=cfg)

    strategy_id = final_state.get("strategy_id")
    if not strategy_id:
        raise RuntimeError("Meerkat이 전략 ID를 반환하지 않았습니다.")

    db = get_db()
    doc = await db[CollectionName.STRATEGIES].find_one({"_id": strategy_id})

    if doc is None:
        raise RuntimeError(f"전략 도큐먼트를 찾을 수 없습니다 (id={strategy_id})")

    doc["_id"] = str(doc["_id"])
    return strategy_id, doc


async def fetch_ohlcv(symbol: str, interval: str, count: int) -> list[dict]:
    """pyupbit으로 OHLCV 데이터를 로드한다.

    BacktestEngine._fetch_ohlcv / LiveEngine._fetch_window 를 통합한 함수.

    Args:
        symbol: 업비트 마켓 코드. 예: 'KRW-BTC'.
        interval: 캔들 단위 문자열. 예: 'day', 'minute60'.
        count: 로드할 캔들 수.

    Returns:
        OHLCV dict 리스트 (timestamp, open, high, low, close, volume).
    """
    df = await asyncio.to_thread(
        pyupbit.get_ohlcv, symbol, interval=interval, count=count,
    )
    if df is None or df.empty:
        return []

    df = df.sort_index()
    return [
        {
            "timestamp": ts.isoformat(),
            "open":   float(row["open"]),
            "high":   float(row["high"]),
            "low":    float(row["low"]),
            "close":  float(row["close"]),
            "volume": float(row["volume"]),
        }
        for ts, row in df.iterrows()
    ]
