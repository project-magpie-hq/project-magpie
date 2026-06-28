import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.owl_director.node import route_after_owl_tools
from magpie_agent.graphs.shared import (
    add_analyze_and_calculate_subgraph,
    add_fox_and_tools,
    add_fox_conditional_edges,
    add_fox_tools_to_subgraph,
    add_hawk_and_tools,
    add_hawk_conditional_edges,
    add_hawk_tools_conditional_edges,
    add_owl_and_tools,
    add_owl_conditional_edges,
    add_owl_tools_conditional_edges,
    add_start_to_owl_edge,
    add_subgraph_to_hawk,
)
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def build_common_graph() -> CompiledStateGraph:
    """사용자 인터랙션 전용 그래프.

    Flow: Owl → Fox → Analyze & Calculate(Meerkat → Calculate Team) → Hawk → Tools → END
    Fox Finder가 후보 코인을 선정하면, Analyze & Calculate 서브그래프에서
    Meerkat의 차트 분석과 Calculate Team(Bull/Bear/Dolphin)의 타점 계산을
    고정된 순서로 실행한다. 마지막으로 Hawk Picker가 최종 종목을 확정한다.
    from_daemon=False, is_daily_review=False 기본값으로 실행됩니다.
    """
    try:
        workflow = StateGraph(MagpieState)

        # 노드 등록
        add_owl_and_tools(workflow)
        add_fox_and_tools(workflow)
        add_analyze_and_calculate_subgraph(workflow)
        add_hawk_and_tools(workflow)

        # 엣지 연결
        add_start_to_owl_edge(workflow)
        add_owl_conditional_edges(workflow)
        add_owl_tools_conditional_edges(workflow, route_after_owl_tools)
        add_fox_conditional_edges(workflow)
        add_fox_tools_to_subgraph(workflow)
        add_subgraph_to_hawk(workflow)
        add_hawk_conditional_edges(workflow)
        add_hawk_tools_conditional_edges(workflow)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("Common 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("Common 그래프 빌드 실패") from e
