"""Calculate Team 서브그래프 빌더

Bull(낙관) → Bear(비관) → Dolphin(중재) 토론을 하나의 재사용 가능한
LangGraph 서브그래프로 구성한다.

Prepare 단계에서 DB로부터 Bull/Bear/Dolphin이 사용할 컨텍스트 데이터를
자체 조회하므로, 부모 그래프가 사전에 데이터를 제공할 필요가 없다.

병렬 실행 구조 (Wave 0 + 3 Wave):
  Wave 0 (진입): prepare → 컨텍스트 데이터 DB 조회 및 세팅
  Wave 1 (병렬): bull_first + bear_first
  Wave 2 (병렬): bear_rebuttal + bull_rebuttal
  Wave 3:         dolphin_judge → END
"""

import logging

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.calculate_team.node import (
    bear_first_node,
    bear_rebuttal_node,
    bull_first_node,
    bull_rebuttal_node,
    dolphin_judge_node,
)
from magpie_agent.agents.calculate_team.prepare import prepare_calculate_data
from magpie_agent.agents.calculate_team.schema import CalculateTeamState

logger = logging.getLogger(__name__)


def build_calculate_team_subgraph() -> CompiledStateGraph:
    """Bull/Bear/Dolphin 토론 서브그래프를 빌드한다.

    prepare 노드에서 DB 조회로 컨텍스트를 자체 조달하므로,
    부모 그래프(Common/DailyReport/TargetRefresh)는
    별도의 데이터 준비 없이 바로 이 서브그래프를 호출할 수 있다.

    Returns:
        CompiledStateGraph: 부모 그래프에서 하나의 노드로 추가 가능한 서브그래프.
    """
    try:
        workflow = StateGraph(CalculateTeamState)

        # Wave 0: 컨텍스트 데이터 준비
        workflow.add_node("prepare", prepare_calculate_data)

        # 노드 등록
        workflow.add_node("bull_first", bull_first_node)
        workflow.add_node("bear_first", bear_first_node)
        workflow.add_node("bull_rebuttal", bull_rebuttal_node)
        workflow.add_node("bear_rebuttal", bear_rebuttal_node)
        workflow.add_node("dolphin_judge", dolphin_judge_node)

        # === Wave 1: prepare → Bull + Bear (병렬) ===
        workflow.add_edge("__start__", "prepare")
        workflow.add_edge("prepare", "bull_first")
        workflow.add_edge("prepare", "bear_first")

        # === Wave 2: Bull/Bear 상호 반박 (병렬) ===
        # Bear가 Bull의 분석을 반박
        workflow.add_edge("bull_first", "bear_rebuttal")
        # Bull이 Bear의 분석을 반박
        workflow.add_edge("bear_first", "bull_rebuttal")

        # === Wave 3: Dolphin 최종 중재 ===
        # 두 반박이 모두 완료된 후 Dolphin이 판결
        workflow.add_edge("bear_rebuttal", "dolphin_judge")
        workflow.add_edge("bull_rebuttal", "dolphin_judge")

        # 종료
        workflow.add_edge("dolphin_judge", END)

        return workflow.compile()

    except Exception as e:
        logger.exception("CalculateTeam 서브그래프 빌드 중 오류 발생")
        raise RuntimeError("CalculateTeam 서브그래프 빌드 실패") from e
