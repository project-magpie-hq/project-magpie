"""Per-Coin Pipeline 서브그래프 빌더

1개 코인에 대해서만 Meerkat(차트 분석) → Calculate Team(Bull/Bear/Dolphin) →
Tools(DB 저장)를 실행하고 결과를 수집한다.

Parallel Coordinator가 여러 코인을 병렬(asyncio.gather)로 실행할 때
각 코인별로 하나씩 생성되는 서브그래프이다.
"""

import logging
import re

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from magpie_agent.agents.calculate_team.subgraph import build_calculate_team_subgraph
from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.meerkat_scanner.node import meerkat_node
from magpie_agent.state.magpie import MagpieState
from magpie_agent.tools.monitor_target import register_monitoring_targets_to_nest

logger = logging.getLogger(__name__)


async def collect_per_coin_result(state: MagpieState) -> dict:
    """Per-Coin Pipeline 종료 시 결과를 수집하여 per_coin_results에 추가한다.

    IMPORTANT: state fields (dolphin_score, bull_analysis, bear_analysis) set
    inside the CalculateTeamState subgraph may NOT propagate back to this
    parent MagpieState due to LangGraph schema mismatch.
    As a fallback, this function extracts data from the messages list
    (which always propagates correctly via add_messages reducer).
    """
    coin = state.get("current_target_coin") or "unknown"

    dolphin_score = state.get("dolphin_score")
    dolphin_reasoning = state.get("dolphin_reasoning", "")
    bull_analysis = state.get("bull_analysis") or ""
    bear_analysis = state.get("bear_analysis") or ""
    chart_context = state.get("chart_context", "")
    current_price = state.get("current_price")

    # Fallback: extract from messages when state fields are empty.
    # State fields set inside the CalculateTeamState subgraph (dolphin_score,
    # bull_analysis, bear_analysis) may not propagate back to this parent
    # MagpieState due to LangGraph's different-state-schema subgraph handling.
    # The messages list always propagates correctly via add_messages reducer.
    messages = state.get("messages", [])

    if dolphin_score is None or dolphin_reasoning == "" or bull_analysis == "" or bear_analysis == "":
        for msg in reversed(messages):
            content = str(getattr(msg, "content", "") or "")
            tool_calls = getattr(msg, "tool_calls", None)

            # Dolphin message: [DOLPHIN_SCORE] or tool_calls
            if (dolphin_score is None or dolphin_reasoning == "") and (
                "[DOLPHIN_SCORE]" in content or tool_calls
            ):
                score_match = re.search(
                    r"\[DOLPHIN_SCORE\]\s*:\s*(-?[0-9]*\.?[0-9]+)", content
                )
                if score_match and dolphin_score is None:
                    try:
                        dolphin_score = max(0.0, min(1.0, float(score_match.group(1))))
                    except ValueError:
                        pass
                if not dolphin_reasoning:
                    dolphin_reasoning = content[:800]

            # Bull analysis (skip rebuttal/dolphin messages)
            if not bull_analysis and (
                ("Bull" in content and ("분석" in content or "관점" in content))
                or ("📈" in content and len(content) > 100)
            ):
                if "[DOLPHIN_SCORE]" not in content and "[Bear의" not in content:
                    bull_analysis = content[:500]

            # Bear analysis (skip rebuttal/dolphin messages)
            if not bear_analysis and (
                ("Bear" in content and ("분석" in content or "관점" in content))
                or ("📉" in content and len(content) > 100)
            ):
                if "[DOLPHIN_SCORE]" not in content and "[Bull의" not in content:
                    bear_analysis = content[:500]

            # chart_context fallback from Meerkat's message
            if not chart_context and content and ("차트" in content or "기술" in content or "분석" in content):
                if "[DOLPHIN_SCORE]" not in content and "Bull" not in content and "Bear" not in content:
                    chart_context = content

        if dolphin_score is not None and not dolphin_reasoning:
            dolphin_reasoning = "(메시지에서 Dolphin 판단 근거를 추출할 수 없음)"

    result_entry = {
        "coin": coin,
        "current_price": current_price if current_price is not None else state.get("current_price"),
        "chart_context": chart_context,
        "dolphin_score": dolphin_score,
        "dolphin_reasoning": dolphin_reasoning,
        "bull_summary": bull_analysis[:500] if bull_analysis else "",
        "bear_summary": bear_analysis[:500] if bear_analysis else "",
    }
    score_str = f"{dolphin_score:.2f}" if dolphin_score is not None else "N/A"
    print(f"   📦 [Collector]: {coin} 분석 결과 수집 완료 (score={score_str})")
    return {"per_coin_results": [result_entry]}


def build_per_coin_pipeline() -> CompiledStateGraph:
    """1개 코인 전용 Meerkat → Calculate Team → Tools 서브그래프를 빌드한다.

    호출 전 state에 current_target_coin과 hawk_candidates=[coin]이 설정되어 있어야 한다.
    실행 완료 후 per_coin_results에 해당 코인의 결과가 추가된다.

    Flow:
      __start__ → Meerkat(chart analysis)
                → Calculate Team(Bull/Bear/Dolphin)
                → Calculate Team Tools(DB 저장)
                → Collector(per_coin_results 수집)
                → END
    """
    try:
        workflow = StateGraph(MagpieState)

        # 1. Meerkat: 단일 코인 차트 분석
        workflow.add_node(NodeNames.MEERKAT_SCANNER.value, meerkat_node)

        # 2. Calculate Team: Bull/Bear/Dolphin 토론
        calc_subgraph = build_calculate_team_subgraph()
        workflow.add_node(NodeNames.CALCULATE_TEAM.value, calc_subgraph)

        # 3. Calculate Team Tools: Dolphin의 타점 저장
        workflow.add_node(
            NodeNames.CALCULATE_TEAM_TOOLS.value,
            ToolNode([register_monitoring_targets_to_nest]),
        )

        # 4. Collector: 결과 취합
        workflow.add_node("collect_result", collect_per_coin_result)

        # 엣지 연결
        workflow.add_edge("__start__", NodeNames.MEERKAT_SCANNER.value)
        workflow.add_edge(NodeNames.MEERKAT_SCANNER.value, NodeNames.CALCULATE_TEAM.value)
        workflow.add_edge(NodeNames.CALCULATE_TEAM.value, NodeNames.CALCULATE_TEAM_TOOLS.value)
        workflow.add_edge(NodeNames.CALCULATE_TEAM_TOOLS.value, "collect_result")
        workflow.add_edge("collect_result", END)

        return workflow.compile()

    except Exception as e:
        logger.exception("PerCoinPipeline 서브그래프 빌드 중 오류 발생")
        raise RuntimeError("PerCoinPipeline 서브그래프 빌드 실패") from e
