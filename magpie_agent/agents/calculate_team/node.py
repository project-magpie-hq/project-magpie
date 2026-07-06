"""Calculate Team 노드 구현

Bull(낙관), Bear(비관), Dolphin(중재) 세 역할이 토론하며 최종 타점을 계산한다.

Flow:
  bull_first + bear_first (병렬)
    → bear_rebuttal + bull_rebuttal (병렬)
    → dolphin_judge (최종 타점 도출, register_monitoring_targets_to_nest 호출)
"""

import logging

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from magpie_agent.agents.calculate_team.schema import CalculateTeamState
from magpie_agent.agents.utils import load_prompt, normalize_content
from magpie_agent.tools.monitor_target import register_monitoring_targets_to_nest
from magpie_agent.tools.telegram import send_telegram_message

logger = logging.getLogger(__name__)

# =========================================================================
# Bull: 낙관적 분석
# =========================================================================


async def bull_first_node(state: CalculateTeamState) -> dict:
    """Bull 1차 분석: 낙관적 관점에서 시장을 분석하고 타점 방향을 제시한다."""
    return await _run_bull_or_bear(state, "prompt_bull.md", "bull_analysis", "Bull")


async def bull_rebuttal_node(state: CalculateTeamState) -> dict:
    """Bull 반박: Bear의 분석을 읽고 Bull 관점에서 반박/보완한다."""
    extra_context = "\n\n[Bear의 초기 분석 (반박 대상)]\n" + (state.get("bear_analysis") or "(Bear 분석 없음)")
    return await _run_bull_or_bear(state, "prompt_bull.md", "bull_rebuttal", "Bull", extra_context=extra_context)


# =========================================================================
# Bear: 비관적 분석
# =========================================================================


async def bear_first_node(state: CalculateTeamState) -> dict:
    """Bear 1차 분석: 비관적/보수적 관점에서 시장을 분석하고 리스크를 평가한다."""
    return await _run_bull_or_bear(state, "prompt_bear.md", "bear_analysis", "Bear")


async def bear_rebuttal_node(state: CalculateTeamState) -> dict:
    """Bear 반박: Bull의 분석을 읽고 Bear 관점에서 반박/보완한다."""
    extra_context = "\n\n[Bull의 초기 분석 (반박 대상)]\n" + (state.get("bull_analysis") or "(Bull 분석 없음)")
    return await _run_bull_or_bear(state, "prompt_bear.md", "bear_rebuttal", "Bear", extra_context=extra_context)


async def _run_bull_or_bear(
    state: CalculateTeamState,
    prompt_file: str,
    output_key: str,
    role_name: str,
    extra_context: str = "",
) -> dict:
    """Bull/Bear 공통 LLM 호출 로직"""
    system_prompt = load_prompt(prompt_file)

    user_input = (
        f"[투자 전략]\n{state.get('strategy_details', '')}\n\n"
        f"[차트 분석 리포트]\n{state.get('chart_context', '')}\n\n"
        f"[직전 타점 피드백]\n{state.get('feedback_data', '(없음)')}\n\n"
        f"[현재 자산]\n{state.get('wallet_data', '(없음)')}\n\n"
        f"[최근 매매 기록]\n{state.get('recent_trades', '(없음)')}\n\n"
        f"[현재 등록된 타점 정보]\n{state.get('existing_targets_clean', '(없음)')}\n\n"
        f"[Hawk Picker 최종 선정 종목]\n{state.get('target_coins', '(없음)')}\n\n"
        f"[트리거 정보]\n{state.get('trigger_info', '(없음)')}"
        f"{extra_context}"
    )

    try:
        llm = _get_debate_llm()
        response: AIMessage = normalize_content(
            await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_input)])
        )
    except Exception as e:
        logger.exception("%s LLM 호출 실패", role_name)
        raise RuntimeError(f"{role_name} 에이전트 실행 중 오류가 발생했습니다.") from e

    print(f"   🐂🐻 [{role_name}]: {output_key} 분석을 완료했습니다.")
    return {output_key: response.content}


# =========================================================================
# Dolphin: 최종 중재 및 타점 계산
# =========================================================================


async def dolphin_judge_node(state: CalculateTeamState) -> dict:
    """Dolphin 심판: Bull과 Bear의 전체 토론을 검토하고 최종 타점을 결정한다.

    register_monitoring_targets_to_nest 도구를 강제 호출하여 결과를 DB에 저장한다.
    """
    system_prompt = load_prompt("prompt_dolphin.md")

    user_input = (
        f"[투자 전략]\n{state.get('strategy_details', '')}\n\n"
        f"[차트 분석 리포트]\n{state.get('chart_context', '')}\n\n"
        f"[직전 타점 피드백]\n{state.get('feedback_data', '(없음)')}\n\n"
        f"[현재 자산]\n{state.get('wallet_data', '(없음)')}\n\n"
        f"[최근 매매 기록]\n{state.get('recent_trades', '(없음)')}\n\n"
        f"[현재 등록된 타점 정보]\n{state.get('existing_targets_clean', '(없음)')}\n\n"
        f"[Hawk Picker 최종 선정 종목]\n{state.get('target_coins', '(없음)')}\n\n"
        f"[트리거 정보]\n{state.get('trigger_info', '(없음)')}\n\n"
        f"[Bull의 초기 분석]\n{state.get('bull_analysis', '(없음)')}\n\n"
        f"[Bear의 초기 분석]\n{state.get('bear_analysis', '(없음)')}\n\n"
        f"[Bull의 반박]\n{state.get('bull_rebuttal', '(없음)')}\n\n"
        f"[Bear의 반박]\n{state.get('bear_rebuttal', '(없음)')}"
    )

    try:
        agent = _get_dolphin_llm()
        response: AIMessage = normalize_content(
            await agent.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=user_input)])
        )
    except Exception as e:
        logger.exception("Dolphin LLM 호출 실패")
        raise RuntimeError("Dolphin 에이전트 실행 중 오류가 발생했습니다.") from e

    # Bull/Bear 토론 요약 + Dolphin 판단 근거를 로깅 및 Telegram 전송
    bull_view = (state.get("bull_analysis") or "")[:400]
    bear_view = (state.get("bear_analysis") or "")[:400]
    bull_rebuttal_view = (state.get("bull_rebuttal") or "")[:300]
    bear_rebuttal_view = (state.get("bear_rebuttal") or "")[:300]
    dolphin_reasoning = (response.content or "")[:800]

    print(f"   🐬 [Dolphin]: 최종 타점 계산 완료 — 총 {len(response.tool_calls or [])}개 도구 호출")
    if dolphin_reasoning:
        print(f"      📝 판단 근거:\n{dolphin_reasoning}")

    if dolphin_reasoning:
        tg_summary = (
            f"🐬 [Dolphin 판결]\n\n"
            f"📈 Bull 관점\n{bull_view}{'...' if len(state.get('bull_analysis') or '') > 400 else ''}\n\n"
            f"📉 Bear 관점\n{bear_view}{'...' if len(state.get('bear_analysis') or '') > 400 else ''}\n\n"
            f"🔄 Bull 반박\n{bull_rebuttal_view}{'...' if len(state.get('bull_rebuttal') or '') > 300 else ''}\n\n"
            f"🔄 Bear 반박\n{bear_rebuttal_view}{'...' if len(state.get('bear_rebuttal') or '') > 300 else ''}\n\n"
            f"⚖️ Dolphin 판단\n{dolphin_reasoning}{'...' if len(response.content or '') > 800 else ''}"
        )
        await send_telegram_message(chat_id=state["user_id"], text=tg_summary)

    # Dolphin 신뢰도 점수 파싱 (content text → regex)
    content_str = str(response.content or "")
    dolphin_score = _parse_dolphin_score(content_str)

    # Fallback: tool_choice="any"로 인해 content가 비어있을 때 tool_calls.args에서 추출
    if dolphin_score is None and response.tool_calls:
        for tc in response.tool_calls:
            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            score_val = args.get("dolphin_score") if isinstance(args, dict) else None
            if score_val is not None:
                try:
                    dolphin_score = max(0.0, min(1.0, float(score_val)))
                    break
                except (ValueError, TypeError):
                    continue

    dolphin_reasoning = (response.content or "")[:800]

    return {
        "messages": [response],
        "dolphin_score": dolphin_score,
        "dolphin_reasoning": dolphin_reasoning,
    }


def _parse_dolphin_score(content: str) -> float | None:
    """Dolphin 응답에서 [DOLPHIN_SCORE]: X.X 형식의 신뢰도 점수를 추출한다."""
    import re

    match = re.search(r"\[DOLPHIN_SCORE\]\s*:\s*(-?[0-9]*\.?[0-9]+)", content)
    if match:
        try:
            score = float(match.group(1))
            return max(0.0, min(1.0, score))  # 0.0~1.0 클램프
        except ValueError:
            return None
    return None


# =========================================================================
# LLM 초기화
# =========================================================================


def _get_debate_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Bull/Bear 분석용 LLM (논쟁적 텍스트 생성, 도구 미바인드)"""
    # 토론은 창의성이 약간 필요하므로 temperature=0.3
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)


def _get_dolphin_llm() -> Runnable[LanguageModelInput, AIMessage]:
    """Dolphin 최종판결용 LLM (정밀함 필요, 도구 강제 바인드)"""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    return llm.bind_tools(
        [register_monitoring_targets_to_nest],
        tool_choice="any",
    )
