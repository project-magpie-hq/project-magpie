import os

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from tools.strategy_tools import get_my_active_strategy, register_strategy_to_nest


def load_prompt():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "owl_director_prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_owl_llm():
    # 1. 사용할 모델
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)

    # 2. 도구(Tool) 바인딩
    tools = [register_strategy_to_nest, get_my_active_strategy]
    llm_with_tools = llm.bind_tools(tools)

    return llm_with_tools


async def owl_node(state: dict):
    agent = get_owl_llm()

    system_prompt = load_prompt()
    # TEMP: USER ID를 위한 임시 코드
    user_context = f"\n[시스템 정보]\n현재 대화 중인 사용자의 user_id는 '{state['user_id']}' 입니다. 도구를 호출할 때 이 ID를 반드시 사용하세요."

    messages_to_llm = [SystemMessage(content=system_prompt + user_context)] + state["messages"]
    response = await agent.ainvoke(messages_to_llm)

    return {"messages": [response]}
