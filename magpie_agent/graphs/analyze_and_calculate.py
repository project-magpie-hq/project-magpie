"""Analyze & Calculate 서브그래프 빌더

Meerkat(차트 분석) → Calculate Team(Bull/Bear/Dolphin 토론)을
고정된 순서로 실행하는 재사용 가능한 LangGraph 서브그래프.

분석 후에는 반드시 타점까지 계산하도록 설계되어 있으며,
Common Graph, Daily Report Graph, Target Refresh Graph 등에서
하나의 노드로 사용할 수 있다.
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


def build_analyze_and_calculate_subgraph() -> CompiledStateGraph:
    """Meerkat 차트 분석 → Calculate Team 타점 계산 서브그래프를 빌드한다.

    Flow:
      __start__ → Meerkat(chart analysis)
                → Calculate Team(Bull/Bear/Dolphin debate)
                → Calculate Team Tools(DB 저장)
                → END

    Meerkat이 차트 분석 리포트를 생성하면 Calculate Team이 이를 입력으로 받아
    Bull/Bear/Dolphin 토론을 수행하고, Dolphin이 register_monitoring_targets_to_nest
    도구를 호출하면 ToolNode가 실행되어 최종 타점을 DB에 저장한다.

    Returns:
        CompiledStateGraph: 부모 그래프에서 하나의 노드로 추가 가능한 서브그래프.
    """
    try:
        workflow = StateGraph(MagpieState)

        # 1. Meerkat: 후보 코인 차트 분석
        workflow.add_node(NodeNames.MEERKAT_SCANNER.value, meerkat_node)

        # 2. Calculate Team: Bull/Bear/Dolphin 토론 서브그래프
        calc_subgraph = build_calculate_team_subgraph()
        workflow.add_node(NodeNames.CALCULATE_TEAM.value, calc_subgraph)

        # 3. Calculate Team Tools: Dolphin의 타점 저장 도구 실행
        workflow.add_node(
            NodeNames.CALCULATE_TEAM_TOOLS.value,
            ToolNode([register_monitoring_targets_to_nest]),
        )

        # 엣지 연결
        workflow.add_edge("__start__", NodeNames.MEERKAT_SCANNER.value)
        workflow.add_edge(NodeNames.MEERKAT_SCANNER.value, NodeNames.CALCULATE_TEAM.value)
        workflow.add_edge(NodeNames.CALCULATE_TEAM.value, NodeNames.CALCULATE_TEAM_TOOLS.value)
        workflow.add_edge(NodeNames.CALCULATE_TEAM_TOOLS.value, END)

        return workflow.compile()

    except Exception as e:
        logger.exception("AnalyzeAndCalculate 서브그래프 빌드 중 오류 발생")
        raise RuntimeError("AnalyzeAndCalculate 서브그래프 빌드 실패") from e
