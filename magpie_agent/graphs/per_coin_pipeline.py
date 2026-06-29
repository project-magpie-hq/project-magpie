"""Per-Coin Pipeline 서브그래프 빌더

1개 코인에 대해서만 Meerkat(차트 분석) → Calculate Team(Bull/Bear/Dolphin) →
Tools(DB 저장)를 실행하고 결과를 수집한다.

Parallel Coordinator가 여러 코인을 병렬(asyncio.gather)로 실행할 때
각 코인별로 하나씩 생성되는 서브그래프이다.
"""

import logging

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
    """Per-Coin Pipeline 종료 시 결과를 수집하여 per_coin_results에 추가한다."""
    coin = state.get("current_target_coin") or "unknown"
    result_entry = {
        "coin": coin,
        "current_price": state.get("current_price"),
        "chart_context": state.get("chart_context", ""),
        "dolphin_score": state.get("dolphin_score"),
        "dolphin_reasoning": state.get("dolphin_reasoning", ""),
        "bull_summary": (state.get("bull_analysis") or "")[:500],
        "bear_summary": (state.get("bear_analysis") or "")[:500],
    }
    print(f"   📦 [Collector]: {coin} 분석 결과 수집 완료 (score={result_entry['dolphin_score']})")
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
