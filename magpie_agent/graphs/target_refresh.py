import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.constant import NodeNames
from magpie_agent.graphs.shared import add_meerkat_and_tools, add_meerkat_conditional_edges, add_meerkat_tools_to_end
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def build_target_refresh_graph() -> CompiledStateGraph:
    """Bat Daemon이 EXPIRED 타점을 다시 WAITING_BUY 후보로 갱신할 때 사용하는 그래프."""
    try:
        workflow = StateGraph(MagpieState)

        add_meerkat_and_tools(workflow)
        workflow.add_edge("__start__", NodeNames.MEERKAT_SCANNER.value)
        add_meerkat_conditional_edges(
            workflow,
            {
                NodeNames.MEERKAT_TOOLS.value: NodeNames.MEERKAT_TOOLS.value,
            },
        )
        add_meerkat_tools_to_end(workflow)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("TargetRefresh 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("TargetRefresh 그래프 빌드 실패") from e
