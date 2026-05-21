import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.hawk_picker.node import (
    hawk_node,
    route_after_hawk,
    route_after_hawk_tools,
)
from magpie_agent.agents.meerkat_scanner.node import meerkat_node, route_after_meerkat
from magpie_agent.agents.owl_director.node import owl_node, route_after_owl, route_after_owl_tools
from magpie_agent.state.magpie import MagpieState
from magpie_agent.tools.hawk import store_hawk_candidates
from magpie_agent.tools.monitor_target import register_monitoring_targets_to_nest
from magpie_agent.tools.router import transfer_to_agent
from magpie_agent.tools.strategy import (
    get_my_active_strategy,
    register_strategy_to_nest,
    update_strategy_target_coins,
)
from magpie_agent.tools.wallet import get_wallet, process_trade_execution

load_dotenv()

logger = logging.getLogger(__name__)


def build_graph() -> CompiledStateGraph:
    """Project Magpie의 전체 워크플로우 그래프 빌드"""
    try:
        workflow = StateGraph(MagpieState)

        # 1. 노드 정의
        # Owl Director: 사용자 응대 및 전략 수립
        workflow.add_node(NodeNames.OWL_DIRECTOR.value, owl_node)
        workflow.add_node(
            NodeNames.OWL_TOOLS.value,
            ToolNode(
                [
                    register_strategy_to_nest,
                    get_my_active_strategy,
                    transfer_to_agent,
                    get_wallet,
                    process_trade_execution,
                ]
            ),
        )

        # Hawk Picker: 종목 선정 (Phase 1: 후보 선정, Phase 2: 최종 선정)
        workflow.add_node(NodeNames.HAWK_PICKER.value, hawk_node)
        workflow.add_node(
            NodeNames.HAWK_TOOLS.value,
            ToolNode(
                [
                    store_hawk_candidates,
                    update_strategy_target_coins,
                ]
            ),
        )

        # Meerkat Scanner: 차트 분석 및 타점 계산
        workflow.add_node(NodeNames.MEERKAT_SCANNER.value, meerkat_node)
        workflow.add_node(NodeNames.MEERKAT_TOOLS.value, ToolNode([register_monitoring_targets_to_nest]))

        # 2. 엣지 연결
        workflow.add_edge(START, NodeNames.OWL_DIRECTOR.value)

        # Owl의 결과에 따른 조건부 분기 (도구 실행, 하위 에이전트 호출, 또는 종료)
        workflow.add_conditional_edges(
            NodeNames.OWL_DIRECTOR.value,
            route_after_owl,
            {
                NodeNames.OWL_TOOLS.value: NodeNames.OWL_TOOLS.value,
                NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
                NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
                END: END,
            },
        )

        # 도구 실행 후: register_strategy_to_nest이면 hawk_picker로, 나머지는 owl_director로
        workflow.add_conditional_edges(
            NodeNames.OWL_TOOLS.value,
            route_after_owl_tools,
            {
                NodeNames.OWL_DIRECTOR.value: NodeNames.OWL_DIRECTOR.value,
                NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
                NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
            },
        )

        # Hawk Picker: 도구 호출 결과에 따른 분기
        workflow.add_conditional_edges(
            NodeNames.HAWK_PICKER.value,
            route_after_hawk,
            {
                NodeNames.HAWK_TOOLS.value: NodeNames.HAWK_TOOLS.value,
                END: END,
            },
        )

        # Hawk Tools 실행 후: store_hawk_candidates이면 meerkat_scanner(chart-only)로,
        # update_strategy_target_coins이면 meerkat_scanner(전체 타점)로
        workflow.add_conditional_edges(
            NodeNames.HAWK_TOOLS.value,
            route_after_hawk_tools,
            {
                NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
                NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
            },
        )

        # Meerkat Scanner: 차트 분석 전용 모드면 hawk_picker로, 전체 타점 계산이면 meerkat_tools로
        workflow.add_conditional_edges(
            NodeNames.MEERKAT_SCANNER.value,
            route_after_meerkat,
            {
                NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
                NodeNames.MEERKAT_TOOLS.value: NodeNames.MEERKAT_TOOLS.value,
            },
        )

        # 타점 등록 도구 실행 후 종료
        workflow.add_edge(NodeNames.MEERKAT_TOOLS.value, END)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("그래프 빌드 실패") from e
