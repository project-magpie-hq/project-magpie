import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.owl_director.node import route_after_owl
from magpie_agent.graphs.shared import (
    add_meerkat_and_tools,
    add_meerkat_tools_to_end,
    add_owl_and_tools,
    add_start_to_owl_edge,
)
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def _bat_echo_route_after_owl_tools(state: MagpieState) -> str:
    """
    BatEcho 모드에서 owl_tools 실행 후 항상 Owl로 복귀.
    Hawk Picker로의 자동 라우팅을 수행하지 않습니다 (BatEcho에는 Hawk 노드가 없음).
    """
    return NodeNames.OWL_DIRECTOR.value


def _bat_echo_owl_routes() -> dict[str, str]:
    """
    BatEcho 모드의 Owl 조건부 라우팅 맵.
    Hawk Picker는 BatEcho 그래프에 존재하지 않으므로, 
    Owl이 Hawk를 호출하려 하면 Meerkat Scanner로 리다이렉트합니다.
    """
    return {
        NodeNames.OWL_TOOLS.value: NodeNames.OWL_TOOLS.value,
        NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
        END: END,
    }


def _bat_echo_route_after_owl(state: MagpieState) -> str:
    """
    BatEcho 전용 Owl 라우터.
    Hawk Picker 호출 요청을 Meerkat Scanner로 리다이렉트합니다.
    """
    messages = state.get("messages", [])
    if not messages:
        return END

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", None)

    if not tool_calls:
        return END

    tool_call = tool_calls[0]
    if tool_call["name"] == "transfer_to_agent":
        next_agent = tool_call["args"]["next_agent"]
        if next_agent == NodeNames.HAWK_PICKER.value:
            logger.info("BatEcho: Owl이 Hawk Picker 호출 → Meerkat Scanner로 리다이렉트")
            return NodeNames.MEERKAT_SCANNER.value
        return next_agent

    return NodeNames.OWL_TOOLS.value


def build_bat_echo_graph() -> CompiledStateGraph:
    """
    BatEcho: Bat Daemon 트리거 전용 그래프
    
    Bat Daemon이 조건 도달을 감지하면 실행됩니다.
    Owl이 신호를 검증하고 (필요시 매매 실행),
    Meerkat Scanner가 기존 종목에 대한 타점만 갱신합니다.
    Hawk Picker (종목 선정) 단계는 제외됩니다.
    """
    try:
        workflow = StateGraph(MagpieState)

        add_owl_and_tools(workflow)
        add_meerkat_and_tools(workflow)

        add_start_to_owl_edge(workflow)

        owl_routes = _bat_echo_owl_routes()
        workflow.add_conditional_edges(
            NodeNames.OWL_DIRECTOR.value,
            _bat_echo_route_after_owl,
            owl_routes,
        )

        workflow.add_conditional_edges(
            NodeNames.OWL_TOOLS.value,
            _bat_echo_route_after_owl_tools,
            {
                NodeNames.OWL_DIRECTOR.value: NodeNames.OWL_DIRECTOR.value,
            },
        )

        # BatEcho: Meerkat은 항상 전체 타점 계산 모드(full timing)로 실행되므로
        # 조건부 분기 없이 바로 meerkat_tools로 연결
        workflow.add_edge(NodeNames.MEERKAT_SCANNER.value, NodeNames.MEERKAT_TOOLS.value)
        add_meerkat_tools_to_end(workflow)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("BatEcho 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("BatEcho 그래프 빌드 실패") from e
