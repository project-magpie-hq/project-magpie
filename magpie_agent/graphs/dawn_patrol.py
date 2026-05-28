import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.owl_director.node import route_after_owl_tools
from magpie_agent.graphs.shared import (
    add_hawk_and_tools,
    add_hawk_conditional_edges,
    add_hawk_tools_conditional_edges,
    add_meerkat_and_tools,
    add_meerkat_conditional_edges,
    add_meerkat_tools_to_end,
    add_owl_and_tools,
    add_owl_conditional_edges,
    add_owl_tools_conditional_edges,
    add_start_to_owl_edge,
)
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def build_dawn_patrol_graph() -> CompiledStateGraph:
    """
    DawnPatrol: 매일 오전 9시 정기 검진 전용 그래프
    
    매일 오전 9시에 실행되어 매매 이력을 분석하고,
    필요시 전략을 수정하며 종목과 타점을 갱신합니다.
    
    NestForge와 동일한 노드 구성을 가지지만,
    Owl이 `is_daily_review=True` 상태에서 실행되어
    정기 검진 전용 프롬프트(prompt_from_dawn.md)를 사용합니다.
    
    Flow: Owl → (전략 수정시: Hawk → Meerkat) / (불필요시: Meerkat) → END
    """
    try:
        workflow = StateGraph(MagpieState)

        add_owl_and_tools(workflow)
        add_hawk_and_tools(workflow)
        add_meerkat_and_tools(workflow)

        add_start_to_owl_edge(workflow)
        add_owl_conditional_edges(workflow)
        add_owl_tools_conditional_edges(workflow, route_after_owl_tools)
        add_hawk_conditional_edges(workflow)
        add_hawk_tools_conditional_edges(workflow)
        add_meerkat_conditional_edges(workflow)
        add_meerkat_tools_to_end(workflow)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("DawnPatrol 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("DawnPatrol 그래프 빌드 실패") from e
