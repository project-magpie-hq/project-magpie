import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from agents.meerkat_scanner.chart_compressor import generate_chart_context
from agents.owl_director.schema import StrategySchema
from agents.utils import load_prompt, normalize_content
from state.magpie import MagpieState
from tools.monitor_target import register_monitoring_targets_to_nest

logger = logging.getLogger(__name__)


async def meerkat_node(state: MagpieState) -> dict[str, Any]:
    """차트 데이터를 분석하여 구체적인 타점을 계산하고 도구를 호출하는 노드"""

    print("\n🦦 [Meerkat]: 차트 데이터를 분석하여 구체적인 타점을 계산합니다...")

    current_strategy = state.get("current_strategy")
    if current_strategy is None:
        print("   ⚠️ [Meerkat]: 전략 정보가 없어 계산을 중단합니다.")
        # transfer_to_agent 호출에 대한 ToolMessage를 합성해야 meerkat_tools가 해당 tool_call을 실행하지 않음
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] == "transfer_to_agent":
                        return {
                            "messages": [
                                ToolMessage(content="전략 정보가 없어 분석을 중단합니다.", tool_call_id=tc["id"])
                            ]
                        }
                break
        return {"messages": []}

    strategy = StrategySchema.model_validate(current_strategy)

    sim_time: str | None = state.get("current_sim_time")  # 라이브면 None, 테스트면 과거 시간

    try:
        chart_context = await generate_chart_context(strategy.target_coins, sim_time)
    except Exception as e:
        logger.exception("차트 컨텍스트 생성 실패: %s", strategy.target_coins)
        raise RuntimeError("차트 데이터 분석 중 오류가 발생했습니다.") from e

    system_prompt = load_prompt()

    # Owl의 마지막 메시지(분석 결과 및 지시사항)를 피드백으로 사용
    messages = state.get("messages", [])
    feedback_data = messages[-1].content if messages else "이전 피드백 없음"

    user_input = f"""
        [Owl의 지시사항 (투자 전략)]
        {strategy.strategy_details}

        [실시간 차트 컨텍스트 (장/단기 요약)]
        {chart_context}

        [직전 타점 피드백 (Self-Correction 용도)]
        {feedback_data}
    """

    llm_messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]

    try:
        agent = get_meerkat_llm()
        response: AIMessage = normalize_content(await agent.ainvoke(llm_messages))
    except Exception as e:
        logger.exception("Meerkat LLM 호출 실패")
        raise RuntimeError("Meerkat 에이전트 실행 중 오류가 발생했습니다.") from e

    print("   ✅ [Meerkat]: 타점 계산을 완료하고 도구 호출을 준비합니다.")

    return {
        "messages": [response],
    }


def get_meerkat_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Meerkat 에이전트 모델 초기화"""
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
        return llm.bind_tools([register_monitoring_targets_to_nest], tool_choice="register_monitoring_targets_to_nest")
    except Exception as e:
        logger.exception("Meerkat LLM 초기화 실패")
        raise RuntimeError("Meerkat LLM 초기화 실패") from e
