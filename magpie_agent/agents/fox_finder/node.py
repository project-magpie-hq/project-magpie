import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.utils import load_prompt, normalize_content
from magpie_agent.state.magpie import MagpieState
from magpie_agent.tools.fox import store_fox_candidates
from magpie_agent.tools.strategy import fetch_strategy_by_user

logger = logging.getLogger(__name__)


async def fox_node(state: MagpieState) -> dict[str, Any]:
    """Fox Finder: Owl의 전략을 분석하여 많은 후보 타겟을 선정하는 노드

    Meerkat의 차트 분석과 Calculate Team의 타점 계산이
    필요한 후보 코인들을 선정한다.
    """
    print("\n🦊 [Fox]: Owl의 전략을 분석하여 후보 코인을 선정합니다...")

    system_prompt = load_prompt()

    strategy = await fetch_strategy_by_user(state["user_id"])
    if strategy is None:
        print("   ⚠️ [Fox]: 전략 정보가 없어 후보 선정을 중단합니다.")
        return {"messages": [AIMessage(content="전략 정보가 없어 후보 선정을 중단합니다.")]}

    strategy_details = strategy.get("strategy_details", {})

    user_input = f"""
    [투자 전략]
    {strategy_details}
    """

    messages_to_llm = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input),
    ]
    agent = get_fox_llm()
    response: AIMessage = normalize_content(await agent.ainvoke(messages_to_llm))

    candidates: list[str] = []
    if response.tool_calls:
        for tc in response.tool_calls:
            if tc["name"] == "store_fox_candidates":
                candidates = tc["args"].get("target_coins", [])

    if not candidates:
        print("   ⚠️ [Fox]: 후보 코인이 선정되지 않았습니다.")
    else:
        print(f"   🦊 [Fox]: {len(candidates)}개 후보 코인 선정 -> {candidates}")

    return {
        "messages": [response],
        "hawk_candidates": candidates if candidates else None,
    }


def get_fox_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Fox Finder LLM 초기화"""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    return llm.bind_tools([store_fox_candidates])


def route_after_fox(state: MagpieState) -> str:
    """Fox 실행 후 라우팅: 도구 호출이 있으면 fox_tools로, 없으면 종료"""
    messages = state.get("messages", [])
    last_msg = messages[-1] if messages else None
    tool_calls = getattr(last_msg, "tool_calls", None)

    if not tool_calls:
        return END

    tool_call = tool_calls[0]
    print(f"   🦊 [Fox]: 도구 호출 결정 -> {tool_call['name']}")
    return NodeNames.FOX_TOOLS.value
