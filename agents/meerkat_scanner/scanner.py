"""
Meerkat Scanner 에이전트 — 백테스트용 전략 설계 노드.

LangGraph 노드로 등록되며, BacktestState를 입력으로 받아
전략을 설계·저장한 뒤 strategy_id와 strategy를 State에 기록한다.

흐름:
  meerkat_scanner_node
      ↓ (tool_calls 있으면)
  tools_node
      ↓
  meerkat_scanner_node (반복)
      ↓ (tool_calls 없으면, "[STRATEGY_READY]" 포함 응답)
  → 종료, state["strategy_id"] / state["strategy"] 세팅
"""

from __future__ import annotations

import json
import logging
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, ToolMessage

from core.llm import LLMModel, create_llm
from tools.db import find_existing_strategy, save_backtest_strategy
from tools.ohlcv import get_ohlcv_tool

load_dotenv()
logger = logging.getLogger(__name__)

_MEERKAT_TOOLS = [get_ohlcv_tool, find_existing_strategy, save_backtest_strategy]


def _load_prompt() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(current_dir, "prompt.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _summarize_ohlcv(candles: list[dict]) -> str:
    """OHLCV 캔들 리스트 → LLM에게 전달할 컴팩트 통계 요약 문자열.

    raw 캔들 전체를 ToolMessage에 포함하면 Groq 무료 티어 TPM 한도를 초과하므로
    핵심 통계만 추출하여 토큰 수를 대폭 줄인다.
    """
    if not candles:
        return "(OHLCV 데이터 없음)"

    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    n = len(candles)

    ma5  = sum(closes[-5:])  / min(5,  n)
    ma20 = sum(closes[-20:]) / min(20, n)
    ma50 = sum(closes[-50:]) / min(50, n)

    recent5 = ", ".join(f"{v:,.0f}" for v in closes[-5:])
    trend   = "상승" if closes[-1] > closes[0] else "하락"

    return (
        f"[OHLCV 요약 — {n}개 캔들 | {candles[0]['timestamp'][:10]} ~ {candles[-1]['timestamp'][:10]}]\n"
        f"  현재가: {closes[-1]:,.0f}  최고: {max(closes):,.0f}  최저: {min(closes):,.0f}\n"
        f"  MA5={ma5:,.0f}  MA20={ma20:,.0f}  MA50={ma50:,.0f}\n"
        f"  최근5봉 종가: [{recent5}]\n"
        f"  전체 추세: {trend} ({(closes[-1]/closes[0]-1)*100:+.1f}%)\n"
        f"  평균 거래량: {sum(volumes)/n:,.0f}"
    )


def _compress_messages(messages: list) -> list:
    """메시지 리스트에서 OHLCV ToolMessage의 raw 캔들 데이터를 통계 요약으로 교체한다.

    LangGraph 메시지 히스토리에는 이전 LLM-tool 왕복 내용이 모두 포함되어 있다.
    OHLCV 캔들 리스트는 수천 토큰에 달해 Groq 무료 티어 TPM 한도를 즉시 초과하므로
    summary 문자열로 교체하여 토큰 수를 ~50토큰 수준으로 축소한다.
    """
    compressed = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                if (
                    isinstance(data, list)
                    and data
                    and isinstance(data[0], dict)
                    and "close" in data[0]
                ):
                    summary = _summarize_ohlcv(data)
                    msg = ToolMessage(
                        content=summary,
                        tool_call_id=msg.tool_call_id,
                        name=getattr(msg, "name", None),
                    )
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        compressed.append(msg)
    return compressed


def get_meerkat_llm(model: LLMModel | None = None):
    # OHLCV 200개 캔들이 메시지 히스토리에 누적되므로 TPM 여유가 큰 8B 모델을 기본으로 사용한다.
    # llama-3.1-8b-instant: Groq 무료 티어 TPM 131,072 (vs llama-3.3-70b의 12,000)
    llm = create_llm(model=model or LLMModel.LLAMA_31_8B, temperature=0.1)
    return llm.bind_tools(_MEERKAT_TOOLS)


async def meerkat_scanner_node(state: dict) -> dict:
    """Meerkat LLM 호출 노드.

    - 시스템 프롬프트에 세션 컨텍스트(symbol, style, user_prompt)를 주입한다.
    - 응답에 '[STRATEGY_READY]' 태그가 포함되면 전략 ID를 State에 반영한다.
    """
    llm = get_meerkat_llm()
    system_prompt = _load_prompt()

    context = (
        "\n\n[시스템 컨텍스트]\n"
        f"- symbol: {state['symbol']}\n"
        f"- style: {state['style']}\n"
        f"- user_prompt: {state['user_prompt']}\n"
    )

    # OHLCV ToolMessage의 raw 캔들 데이터를 통계 요약으로 교체해 토큰 수를 줄인다.
    compressed = _compress_messages(state["messages"])
    messages_to_llm = [SystemMessage(content=system_prompt + context)] + compressed
    response = await llm.ainvoke(messages_to_llm)

    update: dict = {"messages": [response]}

    # "[STRATEGY_READY]" 태그에서 strategy_id 파싱
    if isinstance(response.content, str) and "[STRATEGY_READY]" in response.content:
        m = re.search(r"strategy_id:\s*(\S+)", response.content)
        if m:
            update["strategy_id"] = m.group(1).strip()
            logger.info("[Meerkat] 전략 확정 — strategy_id=%s", update["strategy_id"])

    return update
