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


def build_daily_report_graph() -> CompiledStateGraph:
    """매일 오전 9시 정기 검진 전용 그래프.

    매일 오전 9시에 실행되어 매매 이력을 분석하고,
    필요시 전략을 수정하며 종목과 타점을 갱신합니다.

    Common 그래프와 동일한 노드 구성을 가지지만,
    호출 시 `is_daily_review=True`를 상태에 설정하여
    Owl이 정기 검진 전용 프롬프트(prompt_from_daily.md)를 사용하도록 합니다.

    Flow: Owl(daily prompt) → Fox → Analyze & Calculate → Hawk → Tools → END
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
        logger.exception("DailyReport 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("DailyReport 그래프 빌드 실패") from e
