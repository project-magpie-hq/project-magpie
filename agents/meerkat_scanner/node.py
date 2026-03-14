import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from agents.meerkat_scanner.chart_compressor import generate_chart_context
from tools.monitor_target import register_monitoring_targets_to_nest


def load_prompt() -> str:
    """에이전트 시스템 프롬프트 로드"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_meerkat_llm() -> Any:
    """Meerkat 에이전트 모델 초기화 (모델 유지)"""
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    # Meerkat은 계산된 타점을 항상 저장해야 하므로 도구 호출을 강제함
    return llm.bind_tools([register_monitoring_targets_to_nest], tool_choice="register_monitoring_targets_to_nest")


async def meerkat_node(state: dict[str, Any]) -> dict[str, Any]:
    """차트 데이터를 분석하여 구체적인 타점을 계산하고 도구를 호출하는 노드"""
    print("\n🦦 [Meerkat]: 차트 데이터를 분석하여 구체적인 타점을 계산합니다...")

    strategy = state.get("owl_strategy")
    target_coins = strategy.get("target_coins") if strategy else None

    if not target_coins:
        print("   ⚠️ [Meerkat]: 타겟 코인 정보가 없어 계산을 중단합니다.")
        return {"messages": []}

    sim_time = state.get("current_sim_time")  # 라이브면 None, 테스트면 과거 시간
    chart_context = await generate_chart_context(target_coins, sim_time)

    system_prompt = load_prompt()

    feedback_data = state.get(
        "meerkat_feedback", "최초 타점 계산이므로 이전 피드백이 없습니다. 차트 데이터만으로 최적의 타점을 산출하세요."
    )

    user_input = f"""
[Owl의 지시사항 (투자 전략)]
{strategy.get("strategy_details", "전략 내용 없음")}

[실시간 차트 컨텍스트 (장/단기 요약)]
{chart_context}

[직전 타점 피드백 (Self-Correction 용도)]
{feedback_data}
"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]

    agent = get_meerkat_llm()
    response = await agent.ainvoke(messages)

    print("   ✅ [Meerkat]: 타점 계산을 완료하고 도구 호출을 준비합니다.")

    return {
        "messages": [response],
    }
