import os

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from state.magpie_state import MagpieState
from tools.strategy_tools import get_my_active_strategy, register_strategy_to_nest


def load_prompt():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "owl_director_prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_owl_llm():
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)
    tools = [register_strategy_to_nest, get_my_active_strategy]
    llm_with_tools = llm.bind_tools(tools)

    return llm_with_tools


async def owl_node(state: MagpieState):
    print("\n🦉 [Owl]: 사용자의 요청을 분석하고 다음 행동을 결정합니다...")
    agent = get_owl_llm()

    system_prompt = load_prompt()
    messages_to_llm = [SystemMessage(content=system_prompt)] + state["messages"]
    response = await agent.ainvoke(messages_to_llm)

    updates = {"messages": [response]}
    action_type = "REPLY"

    if state["messages"]:
        last_state_msg = state["messages"][-1]
        if (
            getattr(last_state_msg, "type", "") == "tool"
            and getattr(last_state_msg, "name", "") == "register_strategy_to_nest"
        ):
            action_type = "EXECUTE"

    if response.tool_calls:
        for tool_call in response.tool_calls:
            print(f"   🛠️ [Owl이 도구 호출 시도]: {tool_call['name']}")
            if tool_call["name"] == "register_strategy_to_nest":
                action_type = "EXECUTE"
                updates["owl_strategy"] = tool_call["args"]
            elif tool_call["name"] == "get_my_active_strategy":
                action_type = "REPLY"

    updates["action_type"] = action_type

    return updates


def route_after_owl(state: MagpieState):
    """Owl의 상태를 보고 다음 목적지를 결정하는 스마트 라우터"""
    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]

    # 1. LLM이 도구(Tool)를 호출하겠다고 판단한 경우
    if getattr(last_msg, "tool_calls", None):
        print("\n       🦉 [Owl]: 도구를 호출합니다....")
        return "owl_tools"

    # 2. 도구 실행이 끝났거나 일반 대화를 마친 경우
    # 방금 새로운 전략을 등록했다면(EXECUTE), 미어캣을 깨워서 타점을 계산함
    if state.get("action_type") == "EXECUTE":
        print("\n       🦉 [Owl]: Meerkat Scanner에게 타점 계산을 요청합니다....")
        return "meerkat_scanner"

    # 3. 그 외 단순 답변(REPLY)인 경우 사용자 입력을 기다림
    print("\n       🦉 [Owl]: 단순 답변을 진행합니다....")
    return END
