import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from magpie_agent.agents.meerkat_scanner.chart_compressor import generate_chart_context
from magpie_agent.agents.utils import load_prompt, normalize_content
from magpie_agent.state.magpie import MagpieState
from magpie_agent.tools.monitor_target import fetch_monitoring_targets_by_user
from magpie_agent.tools.strategy import fetch_strategy_by_user

logger = logging.getLogger(__name__)


async def meerkat_node(state: MagpieState) -> dict[str, Any]:
    """Per-Coin Pipeline에서 단일 코인의 차트 데이터를 분석하여 리포트를 생성하는 노드.

    Per-Coin Pipeline(PARALLEL_COORDINATOR)에서 current_target_coin으로 지정된
    1개 코인에 대해서만 차트 분석을 수행한다.
    분석 완료 후 현재가(current_price)를 state에 저장하여 Calculate Team이 참조할 수 있게 한다.
    """
    # 단일 코인: current_target_coin 우선, fallback으로 hawk_candidates 첫 항목
    target_coin: str | None = state.get("current_target_coin")
    if not target_coin:
        candidates = state.get("hawk_candidates") or []
        target_coin = candidates[0] if candidates else None

    if not target_coin:
        print("   ⚠️ [Meerkat]: 분석 대상 코인이 없어 중단합니다.")
        return {"messages": []}

    print(f"\n🦦 [Meerkat]: [{target_coin}] 차트 분석을 실행합니다...")
    backtest_time: str | None = state.get("backtest_time")

    # ==============================
    # 1. 전략 정보 (LLM 분석 컨텍스트용)
    # ==============================
    current_strategy = await fetch_strategy_by_user(state["user_id"])
    strategy_details = (
        str(current_strategy.get("strategy_details", {}))
        if current_strategy
        else "(정보 없음)"
    )

    # ==============================
    # 2. 차트 raw 데이터 수집 (단일 코인)
    # ==============================
    try:
        raw_chart_data = await generate_chart_context([target_coin], backtest_time)
    except Exception as e:
        logger.exception("차트 컨텍스트 생성 실패: %s", target_coin)
        raise RuntimeError("차트 데이터 분석 중 오류가 발생했습니다.") from e

    # ==============================
    # 3. 기존 타점 조회 (LLM 분석 컨텍스트용)
    # ==============================
    existing_targets_str = "(없음)"
    existing_targets = await fetch_monitoring_targets_by_user(state["user_id"])
    if existing_targets:
        clean_targets = []
        for t in existing_targets:
            clean_targets.append(
                {
                    k: t.get(k)
                    for k in (
                        "target_coin",
                        "status",
                        "buy_price_upper_limit",
                        "buy_price_lower_limit",
                        "take_profit_price",
                        "stop_loss_price",
                        "buy_allocation_pct",
                    )
                }
            )
        existing_targets_str = str(clean_targets)

    # ==============================
    # 4. LLM 차트 분석 (strategy + existing targets를 컨텍스트로)
    # ==============================
    system_prompt = load_prompt()

    user_input = f"""
    [분석 대상 코인]
    {target_coin}

    [차트 기술 데이터]
    {raw_chart_data}

    [투자 전략]
    {strategy_details}

    [현재 등록된 타점 정보]
    {existing_targets_str}
    """

    llm = _get_meerkat_llm()
    response: AIMessage = normalize_content(
        await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]
        )
    )

    chart_context = str(response.content) if response.content else ""

    # chart_compressor의 do_chart_analyze 결과에서 현재가 추출
    current_price = _extract_current_price(raw_chart_data)
    if current_price is not None:
        print(f"   💰 [{target_coin}] 현재가: {current_price:,.0f}원")

    print(f"   ✅ [Meerkat]: [{target_coin}] 차트 분석 리포트 생성 완료")
    return {
        "messages": [response],
        "chart_context": chart_context,
        "current_price": current_price,
    }


def _extract_current_price(chart_data: str) -> float | None:
    """차트 raw 데이터에서 현재가를 추출한다.

    chart_compressor 출력 형식:
      [1. 현재가]
      - 현재가: 85,000,000 원
    """
    import re

    match = re.search(r"현재가:\s*([\d,]+)\s*원", chart_data)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except (ValueError, IndexError):
            return None
    return None


def _get_meerkat_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Meerkat 차트 분석용 LLM (분석 텍스트 생성, 도구 미바인드)"""
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
