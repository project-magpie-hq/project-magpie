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
    """차트 데이터를 분석하여 LLM 기반 차트 분석 리포트를 생성하는 노드.

    항상 Hawk Picker로부터 호출되며, AIMessage 리포트를 반환한 후 Hawk Picker로 복귀한다.
    Hawk Phase 2가 이 리포트를 읽고 최종 종목을 선정한 뒤 Calculate Team으로 넘긴다.
    """
    print("\n🦦 [Meerkat]: 차트 분석을 실행합니다...")

    target_coins: list[str] = state.get("hawk_candidates") or []
    backtest_time: str | None = state.get("backtest_time")

    if not target_coins:
        print("   ⚠️ [Meerkat]: hawk_candidates가 없어 분석을 중단합니다.")
        return {"messages": []}

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
    # 2. 차트 raw 데이터 수집
    # ==============================
    try:
        raw_chart_data = await generate_chart_context(target_coins, backtest_time)
    except Exception as e:
        logger.exception("차트 컨텍스트 생성 실패: %s", target_coins)
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
    {target_coins}

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

    print("   ✅ [Meerkat]: 차트 분석 리포트를 생성했습니다. (경로: → Calculate Team)")

    chart_context = str(response.content) if response.content else ""
    return {"messages": [response], "chart_context": chart_context}


def _get_meerkat_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Meerkat 차트 분석용 LLM (분석 텍스트 생성, 도구 미바인드)"""
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
