"""Signal Trigger 서브그래프 빌더

Bat Daemon이 매매 신호(BUY/SELL)를 감지했을 때 호출되는 전용 그래프.

Flow: Owl → Analyze & Calculate(Meerkat → Calculate Team → Tools) → END

Owl은 daemon 프롬프트(prompt_from_daemon.md)를 사용하여 이벤트를 분석하고,
모든 라우팅(END, hawk_picker, fox_finder)은 Analyze & Calculate로 리다이렉트된다.
종목 선정 관련 에이전트(Fox, Hawk, Parallel Coordinator)는 호출하지 않는다.
"""

import logging

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.owl_director.node import route_after_owl_tools
from magpie_agent.graphs.shared import (
    add_analyze_and_calculate_subgraph,
    add_owl_and_tools,
    add_owl_conditional_edges,
    add_owl_tools_conditional_edges,
    add_start_to_owl_edge,
)
from magpie_agent.state.magpie import MagpieState

load_dotenv()

logger = logging.getLogger(__name__)


def build_signal_trigger_graph() -> CompiledStateGraph:
    """Bat Daemon 매매 신호 처리 전용 그래프.

    Bat이 BUY/SELL 신호를 감지하면 실행되어,
    Owl(daemon prompt) → Meerkat → Calculate Team 순서로
    해당 코인의 차트를 재분석하고 타점을 DB에 업데이트한다.

    Flow:
      __start__ → Owl(daemon prompt)
                → (모든 경로) Analyze & Calculate(Meerkat → Calculate Team → Tools)
                → END

    모든 Owl 라우팅(END, hawk_picker, fox_finder)은
    Analyze & Calculate로 리다이렉트되므로,
    종목 선정(Fox, Hawk)이나 병렬 처리(Parallel Coordinator) 없이
    곧바로 차트 분석/타점 계산을 수행한다.
    """
    try:
        workflow = StateGraph(MagpieState)

        # 노드 등록
        add_owl_and_tools(workflow)
        add_analyze_and_calculate_subgraph(workflow)

        # 엣지 연결: Owl이 모든 경로를 Analyze & Calculate로 보냄
        add_start_to_owl_edge(workflow)
        add_owl_conditional_edges(
            workflow,
            owl_routes={
                NodeNames.OWL_TOOLS.value: NodeNames.OWL_TOOLS.value,
                NodeNames.FOX_FINDER.value: NodeNames.ANALYZE_AND_CALCULATE.value,
                NodeNames.HAWK_PICKER.value: NodeNames.ANALYZE_AND_CALCULATE.value,
                END: NodeNames.ANALYZE_AND_CALCULATE.value,
            },
        )
        add_owl_tools_conditional_edges(
            workflow,
            route_after_owl_tools,
            owl_tool_routes={
                NodeNames.OWL_DIRECTOR.value: NodeNames.OWL_DIRECTOR.value,
                NodeNames.FOX_FINDER.value: NodeNames.ANALYZE_AND_CALCULATE.value,
            },
        )

        # Analyze & Calculate 완료 후 종료
        workflow.add_edge(NodeNames.ANALYZE_AND_CALCULATE.value, END)

        memory = MemorySaver()
        return workflow.compile(checkpointer=memory)

    except Exception as e:
        logger.exception("SignalTrigger 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("SignalTrigger 그래프 빌드 실패") from e
