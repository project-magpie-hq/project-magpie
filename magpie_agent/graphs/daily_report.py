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


def build_daily_report_graph() -> CompiledStateGraph:
    """매일 오전 9시 정기 검진 전용 그래프.

    매일 오전 9시에 실행되어 매매 이력을 분석하고,
    필요시 전략을 수정하며 종목과 타점을 갱신합니다.

    Common 그래프와 동일한 노드 구성을 가지지만,
    호출 시 `is_daily_review=True`를 상태에 설정하여
    Owl이 정기 검진 전용 프롬프트(prompt_from_daily.md)를 사용하도록 합니다.

    Flow: Owl(daily prompt) → (전략 수정시: register_strategy → Hawk → Meerkat → Hawk → Calculate Team)
                              / (불필요시: transfer_to_agent("hawk_picker") → Hawk → Calculate Team)
                              → Tools → END
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
        logger.exception("DailyReport 그래프 빌드 중 오류가 발생했습니다.")
        raise RuntimeError("DailyReport 그래프 빌드 실패") from e
