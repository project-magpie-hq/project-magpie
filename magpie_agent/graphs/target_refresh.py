import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.constant import NodeNames
from magpie_agent.graphs.shared import (
    add_analyze_and_calculate_subgraph,
)
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def build_target_refresh_graph() -> CompiledStateGraph:
    """Bat Daemon이 EXPIRED 타점을 다시 WAITING_BUY 후보로 갱신할 때 사용하는 그래프.

    Analyze & Calculate 서브그래프(Meerkat → Calculate Team)를 사용하여
    차트 재분석 및 타점 재계산을 수행한다.
    Prepare 노드가 내장된 Calculate Team 서브그래프가 컨텍스트 데이터를
    자체 조회하므로, 별도의 데이터 준비 단계 없이 바로 실행 가능하다.
    """
    try:
        workflow = StateGraph(MagpieState)

        add_analyze_and_calculate_subgraph(workflow)
        workflow.add_edge("__start__", NodeNames.ANALYZE_AND_CALCULATE.value)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("TargetRefresh 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("TargetRefresh 그래프 빌드 실패") from e
