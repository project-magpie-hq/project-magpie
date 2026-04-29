import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from agents.constant import NodeNames
from agents.owl_director.schema import StrategySchema
from agents.utils import load_prompt, normalize_content
from state.magpie import MagpieState
from tools.router import transfer_to_agent
from tools.strategy import get_my_active_strategy, register_strategy_to_nest

logger = logging.getLogger(__name__)


async def owl_node(state: MagpieState) -> dict[str, Any]:
    """사용자 요청을 분석하고 도구 호출 또는 답변을 생성하는 노드"""
    print("\n\n🦉 [Owl]: 사용자의 요청을 분석하고 있습니다...")

    system_prompt = load_prompt()
    additional_prompt = (
        load_prompt("prompt_from_daemon.md") if state.get("from_daemon") else load_prompt("prompt_from_user.md")
    )

    current_strategy = state.get("current_strategy")

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
                updates["current_strategy"] = strategy_update.model_dump()

    return updates


def get_owl_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Owl 에이전트 모델 초기화"""
    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
        tools = [register_strategy_to_nest, get_my_active_strategy, transfer_to_agent]
        return llm.bind_tools(tools)
    except Exception as e:
        logger.exception("Owl LLM 초기화 실패")
        raise RuntimeError("Owl LLM 초기화 실패") from e


def route_after_owl(state: MagpieState) -> str:
    """메시지 내역을 기반으로 다음 노드로 분기하는 라우터"""
    messages = state.get("messages", [])
    last_msg = messages[-1]

    tool_calls = getattr(last_msg, "tool_calls", None)

    if not tool_calls:
        return END

    tool_call = tool_calls[0]
    if tool_call["name"] == "transfer_to_agent":
        next_agent = tool_call["args"]["next_agent"]
        print(f"   🦉 [Owl]: Sub Agent 호출 ➡️ {next_agent}")
        return next_agent

    return NodeNames.OWL_TOOLS.value


def route_after_owl_tools(state: MagpieState) -> str:
    """owl_tools 실행 후 라우팅: register_strategy_to_nest 실행 시 meerkat_scanner로 자동 이동"""
    messages = state.get("messages", [])
    last_msg = messages[-1]

    if getattr(last_msg, "name", None) == "register_strategy_to_nest":
        print("   🦉 [Owl Tools]: 전략 등록 완료 → Meerkat Scanner 자동 호출")
        return NodeNames.MEERKAT_SCANNER.value

    return NodeNames.OWL_DIRECTOR.value
