import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from agents.meerkat_scanner.chart_compressor import generate_chart_context
from tools.monitor_target_tools import register_monitoring_targets_to_nest


def load_prompt():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "meerkat_scanner_prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_meerkat_llm():
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    tools = [register_monitoring_targets_to_nest]
    llm_with_tools = llm.bind_tools(tools, tool_choice="register_monitoring_targets_to_nest")

    return llm_with_tools


async def meerkat_node(state: dict):
    print("🦦 [Meerkat]: 차트 데이터를 분석하여 구체적인 타점을 계산합니다...")
    agent = get_meerkat_llm()

    strategy = state.get("owl_strategy")
    target_coins = strategy.get("target_coins")

    if not target_coins:
        print("   ⚠️ 타겟 코인이 없어 미어캣이 대기 모드로 전환합니다.")
        return {"meerkat_targets": []}

    chart_context = generate_chart_context(target_coins)
    print(f"   📊 [차트 컨텍스트 주입 완료]\n{chart_context}")

    system_prompt = load_prompt()
    user_input = f"""
[Owl의 지시사항 (전략)]
{strategy.get("strategy_details", "전략 내용 없음")}

[실시간 차트 컨텍스트]
{chart_context}
"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]
    response = await agent.ainvoke(messages)
    print(f"✅ [Meerkat] 타점 계산 완료:\n{response.model_dump_json(indent=2)}")

    return {
        "messages": [response],
    }
