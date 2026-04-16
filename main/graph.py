import logging
from enum import StrEnum

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from agents.beaver_balancer import beaver_balancer
from agents.meerkat_scanner.node import meerkat_node
from agents.owl_director.node import owl_node, route_after_owl
from state.magpie import MagpieState
from tools.monitor_target import register_monitoring_targets_to_nest
from tools.strategy import get_my_active_strategy, register_strategy_to_nest

load_dotenv()

logger = logging.getLogger(__name__)


class NodeNames(StrEnum):
    OWL_DIRECTOR = "owl_director"
    OWL_TOOLS = "owl_tools"
    MEERKAT_SCANNER = "meerkat_scanner"
    MEERKAT_TOOLS = "meerkat_tools"
    BEAVER_BALANCER = "beaver_balancer"


def route_from_start(state: MagpieState) -> str:
    if state.get("trigger_event"):
        return NodeNames.NODE_BEAVER_BALANCER.value
    return NodeNames.OWL_DIRECTOR.value


def build_graph() -> CompiledStateGraph:
    """Project Magpie의 전체 워크플로우 그래프 빌드"""
    try:
        workflow = StateGraph(MagpieState)

        # 1. 노드 정의
        # Owl Director: 사용자 응대 및 전략 수립
        workflow.add_node(NodeNames.OWL_DIRECTOR.value, owl_node)
        workflow.add_node(NodeNames.OWL_TOOLS.value, ToolNode([get_my_active_strategy, register_strategy_to_nest]))

        # Meerkat Scanner: 차트 분석 및 타점 계산
        workflow.add_node(NodeNames.MEERKAT_SCANNER.value, meerkat_node)
        workflow.add_node(NodeNames.MEERKAT_TOOLS.value, ToolNode([register_monitoring_targets_to_nest]))

        # Beaver Balancer: 자산 분배
        workflow.add_node(NodeNames.BEAVER_BALANCER.value, beaver_balancer.beaver_node)

        # 2. 엣지 연결
        workflow.add_conditional_edges(
            START,
            route_from_start,
            {
                NodeNames.BEAVER_BALANCER.value: NodeNames.BEAVER_BALANCER.value,
                NodeNames.OWL_DIRECTOR.value: NodeNames.OWL_DIRECTOR.value,
            },
        )

        workflow.add_edge(NodeNames.BEAVER_BALANCER.value, NodeNames.OWL_DIRECTOR.value)

        # Owl의 결과에 따른 조건부 분기 (도구 실행, 미어캣 호출, 또는 종료)
        workflow.add_conditional_edges(
            NodeNames.OWL_DIRECTOR.value,
            route_after_owl,
            {
                NodeNames.OWL_TOOLS.value: NodeNames.OWL_TOOLS.value,
                NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
                END: END,
            },
        )

        # 도구 실행 후에는 다시 Owl에게 돌아가 결과를 보고하거나 다음 단계를 판단함
        workflow.add_edge(NodeNames.OWL_TOOLS.value, NodeNames.OWL_DIRECTOR.value)

        # 미어캣 타점 계산 후에는 타점 등록 도구 실행
        workflow.add_edge(NodeNames.MEERKAT_SCANNER.value, NodeNames.MEERKAT_TOOLS.value)
        workflow.add_edge(NodeNames.MEERKAT_TOOLS.value, END)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("그래프 빌드 실패") from e
