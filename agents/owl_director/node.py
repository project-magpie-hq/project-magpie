import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from agents.owl_director.schema import StrategySchema
from agents.utils import load_prompt, normalize_content
from state.magpie import MagpieState
from tools.strategy import fetch_active_strategy_for_user, get_my_active_strategy, register_strategy_to_nest

logger = logging.getLogger(__name__)


async def owl_node(state: MagpieState) -> dict[str, Any]:
    """사용자 요청을 분석하고 도구 호출 또는 답변을 생성하는 노드"""
    print("\n\n🦉 [Owl]: 사용자의 요청을 분석하고 있습니다...")

    system_prompt = load_prompt()
    additional_prompt = (
        load_prompt("prompt_from_daemon.md") if state.get("from_daemon") else load_prompt("prompt_from_user.md")
    )

    current_strategy = state.get("current_strategy")
    if current_strategy is None:
        try:
            current_strategy = await fetch_active_strategy_for_user(state["user_id"])
            if current_strategy is None:
                current_strategy = "현재 시스템에 적용된 매매 전략 없음"
        except Exception as e:
            logger.error(f"user id is not exist: {e}")
            raise e

    injected_prompt = system_prompt + additional_prompt + f"\n[현재 시스템에 적용된 매매 전략]\n{current_strategy}\n"

    messages_to_llm = [SystemMessage(content=injected_prompt)] + state["messages"]

    try:
        agent = get_owl_llm()
        response: AIMessage = normalize_content(await agent.ainvoke(messages_to_llm))
    except Exception as e:
        logger.exception("Owl LLM 호출 실패")
        raise RuntimeError("Owl 에이전트 실행 중 오류가 발생했습니다.") from e

    updates: dict[str, Any] = {"messages": [response]}

    if response.tool_calls:
        for tool_call in response.tool_calls:
            print(f"   🛠️ [Owl]: 도구 호출 결정 -> {tool_call['name']}")
            if tool_call["name"] == "register_strategy_to_nest":
                strategy_update = StrategySchema(
                    target_coins=tool_call["args"].get("target_coins", []),
                    strategy_details=tool_call["args"].get("strategy_details", {}),
                )
                updates["owl_strategy"] = strategy_update.model_dump()

    # TODO: next agent 를 리턴하도록 Structure Output 지정
    updates["next_agent"] = ""
    return updates


def get_owl_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Owl 에이전트 모델 초기화"""
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
        tools = [register_strategy_to_nest, get_my_active_strategy]
        return llm.bind_tools(tools)
    except Exception as e:
        logger.exception("Owl LLM 초기화 실패")
        raise RuntimeError("Owl LLM 초기화 실패") from e


def route_after_owl(state: MagpieState) -> str:
    """메시지 내역을 기반으로 다음 노드로 분기하는 라우터"""
    messages = state.get("messages", [])
    last_msg = messages[-1]

    if getattr(last_msg, "tool_calls", None):
        return "owl_tools"

    if state.get("next_agent"):
        print(f"   🦉 [Owl]: Sub Agent 호출 ➡️ {state.get('next_agent')}")
        return state.get("next_agent")

    return END
