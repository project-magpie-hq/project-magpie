"""
Owl Director 의사결정 모듈.

매 타임스텝마다 BacktestEngine 또는 LiveEngine이 직접 호출한다.
LangGraph 노드가 아닌 단순 async 함수로 구현하여 루프 오버헤드를 최소화한다.

입력:
  - ohlcv_window : 현재 시점까지의 OHLCV 캔들 리스트 (최근 N개)
  - strategy     : Meerkat이 설계한 전략 dict
  - current_ts   : 현재 시뮬레이션/실거래 시각 문자열

출력:
  OwlDecision(action, reasoning, confidence)
"""

from __future__ import annotations

import json
import logging
from enum import Enum

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from core.llm import LLMModel, create_llm

load_dotenv()
logger = logging.getLogger(__name__)

_OWL_SYSTEM_PROMPT = """
너는 Project Magpie의 의사결정 에이전트 'Owl Director'야.
백테스트 시뮬레이터로부터 현재 시점의 OHLCV 캔들 데이터와 투자 전략을 전달받아,
'BUY', 'SELL', 'HOLD' 중 하나를 결정하고 그 근거를 설명해야 해.

[규칙]
- 전략에 정의된 지표(RSI, MACD, EMA 등)와 각 지표의 weight를 반드시 고려해.
- 응답은 반드시 아래 JSON 형식 **만** 출력해. 다른 텍스트는 절대 포함하지 마.
- confidence는 0.0 ~ 1.0 사이의 숫자야.

{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": <float>,
  "reasoning": "<한국어로 판단 근거 2~3문장>"
}
""".strip()


# ---------------------------------------------------------------------------
# LLM 인스턴스 재사용 (모듈 레벨 lazy singleton)
# ---------------------------------------------------------------------------

_owl_llm: BaseChatModel | None = None


def _get_owl_llm() -> BaseChatModel:
    """Owl 전용 LLM 인스턴스를 반환한다 (최초 1회만 생성)."""
    global _owl_llm
    if _owl_llm is None:
        _owl_llm = create_llm(
            model=LLMModel.LLAMA_33_70B,
            temperature=0.0,
        )
    return _owl_llm


# ---------------------------------------------------------------------------
# 의사결정 결과 모델
# ---------------------------------------------------------------------------

class OwlAction(str, Enum):
    """Owl이 선택 가능한 액션."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OwlDecision(BaseModel):
    """Owl Director의 단일 의사결정 결과."""

    action: OwlAction = OwlAction.HOLD
    """선택된 액션."""

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    """판단 확신도 (0.0 ~ 1.0)."""

    reasoning: str = ""
    """판단 근거 (한국어)."""


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _build_user_message(ohlcv_window: list[dict], strategy: dict, current_ts: str) -> str:
    # 최근 5개 캔들만 텍스트로 요약 (토큰 절약)
    recent = ohlcv_window[-5:] if len(ohlcv_window) >= 5 else ohlcv_window
    candle_summary = "\n".join(
        f"  [{c['timestamp']}] O={c['open']} H={c['high']} L={c['low']} C={c['close']} V={c['volume']:.0f}"
        for c in recent
    )

    # 간단한 기술 계산값 추가 (close 이동평균)
    closes = [c["close"] for c in ohlcv_window]
    ma5  = sum(closes[-5:])  / min(5,  len(closes))
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    ma50 = sum(closes[-50:]) / min(50, len(closes))

    last_close = closes[-1]
    price_change_pct = ((last_close - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0.0

    return (
        f"[현재 시각] {current_ts}\n\n"
        f"[최근 캔들 (최근 5개)]\n{candle_summary}\n\n"
        f"[보조 계산값]\n"
        f"  현재가: {last_close:,.0f}  전봉 대비: {price_change_pct:+.2f}%\n"
        f"  MA5={ma5:,.0f}  MA20={ma20:,.0f}  MA50={ma50:,.0f}\n\n"
        f"[전략]\n{json.dumps(strategy, ensure_ascii=False, indent=2, default=str)}"
    )


# ---------------------------------------------------------------------------
# 메인 함수
# ---------------------------------------------------------------------------

async def owl_decide(
    ohlcv_window: list[dict],
    strategy: dict,
    current_ts: str,
) -> OwlDecision:
    """현재 OHLCV 윈도우와 전략을 기반으로 BUY/SELL/HOLD 결정을 반환한다."""
    llm = _get_owl_llm()

    user_msg = _build_user_message(ohlcv_window, strategy, current_ts)
    response = await llm.ainvoke(
        [
            SystemMessage(content=_OWL_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ]
    )

    raw = response.content
    if isinstance(raw, list):
        raw = "".join(str(item) for item in raw)
    raw = raw.strip()

    # JSON 코드블록 제거
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
        action_str = parsed.get("action", "HOLD").upper()
        try:
            action = OwlAction(action_str)
        except ValueError:
            action = OwlAction.HOLD

        decision = OwlDecision(
            action=action,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", ""),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("[Owl] JSON 파싱 실패, HOLD 처리. raw=%s", raw[:200])
        decision = OwlDecision(
            action=OwlAction.HOLD,
            confidence=0.0,
            reasoning=raw[:300],
        )

    logger.info(
        "[Owl] %s → %s (conf=%.2f) | %s",
        current_ts, decision.action.value, decision.confidence, decision.reasoning[:60],
    )
    return decision
