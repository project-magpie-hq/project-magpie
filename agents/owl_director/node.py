import os
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from state.magpie import MagpieState
from tools.strategy import get_my_active_strategy, register_strategy_to_nest


def load_prompt() -> str:
    """에이전트 시스템 프롬프트 로드"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_owl_llm() -> Any:
    """Owl 에이전트 모델 초기화 (모델명 유지)"""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)
    # llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    tools = [
        register_strategy_to_nest,
        get_my_active_strategy,
    ]
    return llm.bind_tools(tools)


async def owl_node(state: MagpieState) -> dict[str, Any]:
    """사용자 요청을 분석하고 도구 호출 또는 답변을 생성하는 노드"""
    print("\n\n🦉 [Owl]: 사용자의 요청을 분석하고 있습니다...")

    system_prompt = load_prompt()
    current_strategy = state.get("owl_strategy")

    injected_prompt = (
        system_prompt
        + f"\n\n[현재 시스템에 적용된 매매 전략]\n{current_strategy}\n"
        + "(※ 이 전략이 현재 유효하다면 별도의 도구 호출 없이 Meerkat에게 넘길 피드백만 작성하세요.)"
    )

    messages_to_llm = [SystemMessage(content=injected_prompt)] + state["messages"]

    agent = get_owl_llm()
    response = await agent.ainvoke(messages_to_llm)

    updates = {"messages": [response]}

    if response.tool_calls:
        for tool_call in response.tool_calls:
            print(f"   🛠️ [Owl]: 도구 호출 결정 -> {tool_call['name']}")
            if tool_call["name"] == "register_strategy_to_nest":
                new_strat = {
                    "target_coins": tool_call["args"].get("target_coins"),
                    "strategy_details": tool_call["args"].get("strategy_details"),
                }
                updates["owl_strategy"] = new_strat
                updates["is_strategy_updated"] = True

    return updates


def route_after_owl(state: MagpieState) -> str:
    """메시지 내역을 기반으로 다음 노드로 분기하는 라우터"""
    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]

    if getattr(last_msg, "tool_calls", None):
        return "owl_tools"

    is_system_event = False
    for msg in reversed(messages):
        if msg.type in ["user", "human"]:
            if "SYSTEM_EVENT" in msg.content:
                is_system_event = True
            break

    if is_system_event:
        print("   🦉 [Owl]: 분석 및 지시 완료. Meerkat으로 넘어갑니다 ➡️")
        return "meerkat_scanner"

    if state.get("is_strategy_updated"):
        print("   🦉 [Owl]: 전략 갱신 완료. Meerkat으로 넘어갑니다 ➡️")
        return "meerkat_scanner"

    return END
