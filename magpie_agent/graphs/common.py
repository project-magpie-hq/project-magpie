import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.owl_director.node import route_after_owl_tools
from magpie_agent.graphs.shared import (
    add_calculate_team,
    add_calculate_team_to_tools,
    add_calculate_team_tools_to_end,
    add_hawk_and_tools,
    add_hawk_conditional_edges,
    add_hawk_tools_conditional_edges,
    add_meerkat_and_tools,
    add_meerkat_to_hawk,
    add_owl_and_tools,
    add_owl_conditional_edges,
    add_owl_tools_conditional_edges,
    add_start_to_owl_edge,
)
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def build_common_graph() -> CompiledStateGraph:
    """사용자 인터랙션 전용 그래프.

    Flow: Owl → Hawk(Phase1) → Meerkat(chart) → Hawk(Phase2) → Calculate Team → Tools → END
    Meerkat의 차트 분석 결과를 Hawk가 최종 선정에 활용한 뒤,
    Calculate Team(Bull/Bear/Dolphin)이 직접 타점을 계산합니다.
    from_daemon=False, is_daily_review=False 기본값으로 실행됩니다.
    """
    try:
        workflow = StateGraph(MagpieState)

        add_owl_and_tools(workflow)
        add_hawk_and_tools(workflow)
        add_meerkat_and_tools(workflow)
        add_calculate_team(workflow)

        add_start_to_owl_edge(workflow)
        add_owl_conditional_edges(workflow)
        add_owl_tools_conditional_edges(workflow, route_after_owl_tools)
        add_hawk_conditional_edges(workflow)
        add_hawk_tools_conditional_edges(workflow)
        add_meerkat_to_hawk(workflow)
        add_calculate_team_to_tools(workflow)
        add_calculate_team_tools_to_end(workflow)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("Common 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("Common 그래프 빌드 실패") from e
