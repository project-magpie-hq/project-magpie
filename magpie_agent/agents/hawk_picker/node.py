import logging
from typing import Any, cast

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.utils import load_prompt, normalize_content
from magpie_agent.state.magpie import MagpieState
from magpie_agent.tools.hawk import store_hawk_candidates
from magpie_agent.tools.strategy import fetch_strategy_by_user, update_strategy_target_coins
from magpie_agent.tools.telegram import send_telegram_message

logger = logging.getLogger(__name__)


async def hawk_node(state: MagpieState) -> dict[str, Any]:
    """Hawk Picker: 전략을 분석하여 종목을 선정하는 노드"""
    is_phase2 = bool(state.get("hawk_candidates"))

    if is_phase2:
        print("\n🦅 [Hawk]: 차트 분석 결과를 바탕으로 최종 종목을 선정합니다...")
        system_prompt = (
            load_prompt()
            + "\n\n## 현재 단계: Phase 2 - 최종 종목 선정\n"
            + "차트 분석 결과를 바탕으로 최종 종목을 선정하고 "
            + "update_strategy_target_coins 도구를 호출하여 전략에 반영하세요."
        )

        chart_analysis = state["messages"][-1].content if state.get("messages") else ""

        strategy = await fetch_strategy_by_user(state["user_id"])
        strategy_details = strategy.get("strategy_details", {}) if strategy else {}

        user_input = f"""
        [투자 전략]
        {strategy_details}

        [차트 분석 결과]
        {chart_analysis}
        """

        messages_to_llm = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]
        agent = get_hawk_llm(phase=2)
        response_phase2: AIMessage = normalize_content(await agent.ainvoke(messages_to_llm))

        reasoning = cast(str, response_phase2.content or "").strip()
        target_coins: list[str] = []
        if response_phase2.tool_calls:
            for tc in response_phase2.tool_calls:
                if tc["name"] == "update_strategy_target_coins":
                    target_coins = tc["args"].get("target_coins", [])

        if reasoning and target_coins:
            reason_snippet = reasoning[:500]
            await send_telegram_message(
                chat_id=state["user_id"],
                text=(
                    "🦅 [최종 종목 선정]\n"
                    f"Hawk Picker가 최종 종목을 선정했습니다.\n"
                    f"• 선정 종목: {', '.join(target_coins)}\n"
                    f"• Calculate Team이 타점을 계산합니다.\n\n"
                    f"📝 선정 근거\n{reason_snippet}{'...' if len(reasoning) > 500 else ''}"
                ),
            )

        return {
            "messages": [response_phase2],
        }

    else:
        print("\n🦅 [Hawk]: 투자 전략을 분석하여 후보 종목을 선정합니다...")
        system_prompt = (
            load_prompt()
            + "\n\n## 현재 단계: Phase 1 - 후보 종목 선정\n"
            + "투자 전략을 분석하여 차트 분석이 필요한 후보 코인 리스트를 "
            + "store_hawk_candidates 도구를 호출하여 등록하세요."
        )

        strategy = await fetch_strategy_by_user(state["user_id"])
        if strategy is None:
            print("   ⚠️ [Hawk]: 전략 정보가 없어 종목 선정을 중단합니다.")
            return {"messages": [AIMessage(content="전략 정보가 없어 종목 선정을 중단합니다.")]}

        strategy_details = strategy.get("strategy_details", {})

        user_input = f"""
        [투자 전략]
        {strategy_details}
        """

        messages_to_llm = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]
        agent = get_hawk_llm(phase=1)
        response_phase1: AIMessage = normalize_content(await agent.ainvoke(messages_to_llm))

        candidates: list[str] = []
        if response_phase1.tool_calls:
            for tc in response_phase1.tool_calls:
                if tc["name"] == "store_hawk_candidates":
                    candidates = tc["args"].get("target_coins", [])

        if not candidates:
            print("   ⚠️ [Hawk]: 후보 코인이 선정되지 않았습니다.")
        else:
            print(f"   🦅 [Hawk]: {len(candidates)}개 후보 코인 선정 -> {candidates}")

        return {
            "messages": [response_phase1],
            "hawk_candidates": candidates if candidates else None,
        }


def get_hawk_llm(phase: int = 1) -> Runnable[LanguageModelInput, AIMessage]:
    """Hawk 에이전트 모델 초기화"""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    if phase == 1:
        return llm.bind_tools([store_hawk_candidates])
    else:
        return llm.bind_tools([update_strategy_target_coins])


def route_after_hawk(state: MagpieState) -> str:
    """Hawk 실행 후 라우팅: 도구 호출이 있으면 hawk_tools로, 없으면 종료"""
    messages = state.get("messages", [])
    last_msg = messages[-1] if messages else None
    tool_calls = getattr(last_msg, "tool_calls", None)

    if not tool_calls:
        return END

    tool_call = tool_calls[0]
    print(f"   🦅 [Hawk]: 도구 호출 결정 -> {tool_call['name']}")
    return NodeNames.HAWK_TOOLS.value


def route_after_hawk_tools(state: MagpieState) -> str:
    """hawk_tools 실행 후 라우팅"""
    messages = state.get("messages", [])
    last_msg = messages[-1] if messages else None
    tool_name = getattr(last_msg, "name", None)

    if tool_name == "store_hawk_candidates":
        print("   🦅 [Hawk Tools]: 후보 코인 등록 완료 → Meerkat 차트 분석 호출")
        return NodeNames.MEERKAT_SCANNER.value
    elif tool_name == "update_strategy_target_coins":
        print("   🦅 [Hawk Tools]: 최종 코인 전략 업데이트 완료 → Calculate Team 타점 계산 호출")
        return NodeNames.CALCULATE_TEAM.value

    return NodeNames.HAWK_PICKER.value
