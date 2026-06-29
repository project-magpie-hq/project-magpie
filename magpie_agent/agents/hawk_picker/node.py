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
from magpie_agent.tools.strategy import fetch_strategy_by_user, update_strategy_target_coins
from magpie_agent.tools.telegram import send_telegram_message

logger = logging.getLogger(__name__)


async def hawk_node(state: MagpieState) -> dict[str, Any]:
    """Hawk Picker: Per-Coin Pipeline 병렬 처리 결과를 바탕으로 최종 종목을 선정하는 노드

    Parallel Coordinator가 각 코인에 대해 Meerkat/Calculate Team을 실행한
    per_coin_results를 검토하고, 최종 투자 종목을 확정한다.
    각 코인의 dolphin_score, dolphin_reasoning, Bull/Bear 요약을 참고하여
    신뢰도가 높은 종목을 선정한다.
    """
    print("\n🦅 [Hawk]: Per-Coin Pipeline 결과를 바탕으로 최종 종목을 선정합니다...")
    system_prompt = (
        load_prompt()
        + "\n\n## 현재 단계: 최종 종목 선정\n"
        + "Parallel Coordinator가 각 코인에 대해 Per-Coin Pipeline(Meerkat 차트 분석 + "
        + "Calculate Team 타점 계산)을 병렬 실행한 결과를 검토하고 "
        + "최종 종목을 선정하여 update_strategy_target_coins 도구를 호출하세요."
    )

    per_coin_results = state.get("per_coin_results") or []
    target_coins_input = ", ".join(r.get("coin", "") for r in per_coin_results if r.get("coin"))

    # Per-Coin 결과를 가독성 좋은 텍스트로 변환
    per_coin_summary_lines = []
    for r in per_coin_results:
        coin = r.get("coin", "?")
        score = r.get("dolphin_score")
        score_str = f"{score:.2f}" if score is not None else "N/A"
        reasoning = (r.get("dolphin_reasoning") or "")[:200]
        bull = (r.get("bull_summary") or "")[:200]
        bear = (r.get("bear_summary") or "")[:200]
        price = r.get("current_price")
        price_str = f"{price:,.0f}원" if price is not None else "N/A"
        error = r.get("error")
        if error:
            per_coin_summary_lines.append(
                f"[{coin}] ❌ 분석 실패 — {error}"
            )
        else:
            per_coin_summary_lines.append(
                f"[{coin}] 신뢰도={score_str} | 현재가={price_str}\n"
                f"  Dolphin: {reasoning}{'...' if len(r.get('dolphin_reasoning', '') or '') > 200 else ''}\n"
                f"  Bull: {bull}{'...' if len(r.get('bull_summary', '') or '') > 200 else ''}\n"
                f"  Bear: {bear}{'...' if len(r.get('bear_summary', '') or '') > 200 else ''}"
            )
    per_coin_block = "\n\n".join(per_coin_summary_lines) if per_coin_summary_lines else "(결과 없음)"

    strategy = await fetch_strategy_by_user(state["user_id"])
    strategy_details = strategy.get("strategy_details", {}) if strategy else {}

    user_input = f"""
    [투자 전략]
    {strategy_details}

    [Per-Coin 분석 결과]
    {per_coin_block}

    [분석 완료 코인 목록]
    {target_coins_input}
    """

    messages_to_llm = [SystemMessage(content=system_prompt), HumanMessage(content=user_input)]
    agent = get_hawk_llm()
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
                f"• 해당 종목의 타점이 DB에 등록되었습니다.\n\n"
                f"📝 선정 근거\n{reason_snippet}{'...' if len(reasoning) > 500 else ''}"
            ),
        )

    return {
        "messages": [response_phase2],
    }


def get_hawk_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Hawk 에이전트 모델 초기화"""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
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
    """hawk_tools 실행 후 라우팅: 최종 선정 완료 후 종료"""
    messages = state.get("messages", [])
    last_msg = messages[-1] if messages else None
    tool_name = getattr(last_msg, "name", None)

    if tool_name == "update_strategy_target_coins":
        print("   🦅 [Hawk Tools]: 최종 종목 전략 업데이트 완료")
        return END

    print("   ⚠️ [Hawk Tools]: 알 수 없는 도구 호출, 종료합니다.")
    return END
