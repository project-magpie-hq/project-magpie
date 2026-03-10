import os
from typing import Any

from langchain_core.messages import SystemMessage, ToolMessage
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
    tools = [register_strategy_to_nest, get_my_active_strategy]
    return llm.bind_tools(tools)


async def owl_node(state: MagpieState) -> dict[str, Any]:
    """사용자 요청을 분석하고 도구 호출 또는 답변을 생성하는 노드"""
    print("\n🦉 [Owl]: 사용자의 요청을 분석하고 있습니다...")

    system_prompt = load_prompt()
    messages_to_llm = [SystemMessage(content=system_prompt)] + state["messages"]

    agent = get_owl_llm()
    response = await agent.ainvoke(messages_to_llm)

    updates = {"messages": [response]}

    # 새로운 도구 호출 여부 확인 및 전략 데이터 상태 업데이트
    if response.tool_calls:
        for tool_call in response.tool_calls:
            print(f"   🛠️ [Owl]: 도구 호출 결정 -> {tool_call['name']}")
            if tool_call["name"] == "register_strategy_to_nest":
                # 전략 데이터를 상태에 미리 저장하여 Meerkat이 즉시 참조 가능하게 함
                updates["owl_strategy"] = tool_call["args"]

    return updates


def route_after_owl(state: MagpieState) -> str:
    """메시지 내역을 기반으로 다음 노드로 분기하는 라우터"""
    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]

    # 1. LLM이 도구(Tool) 호출을 결정한 경우 (AIMessage with tool_calls)
    if getattr(last_msg, "tool_calls", None):
        return "owl_tools"

    # 2. 메시지 내역을 역순으로 확인하여 '가장 최근에 실행된 도구'가 무엇인지 파악
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            if msg.name == "register_strategy_to_nest":
                print("       🦉 [Owl]: 전략 등록이 완료되었습니다. Meerkat Scanner를 호출합니다.")
                return "meerkat_scanner"
            # 전략 등록이 아닌 다른 도구(전략 조회 등)라면 더 이상 추적하지 않고 종료
            break
        # 도구 실행 후 Owl이 이미 한 번 응답했다면, 그 응답이 최신이므로 루프를 통해 ToolMessage를 찾게 됨
        # 만약 너무 오래전 대화라면(중간에 일반 AI 메시지가 너무 많으면) 중단할 수 있으나,
        # 보통 Tool 실행 -> Owl 응답 -> Router 순이므로 break 없이 찾습니다.

    return END
