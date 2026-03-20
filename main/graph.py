from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agents.meerkat_scanner.node import meerkat_node
from agents.owl_director.node import owl_node, route_after_owl
from state.magpie import MagpieState
from tools.monitor_target import register_monitoring_targets_to_nest
from tools.strategy import get_my_active_strategy, register_strategy_to_nest

load_dotenv()


def build_graph():
    """Project Magpie의 전체 워크플로우 그래프 빌드"""
    workflow = StateGraph(MagpieState)

    # 1. 노드 정의
    # Owl Director: 사용자 응대 및 전략 수립
    workflow.add_node("owl_director", owl_node)
    workflow.add_node("owl_tools", ToolNode([get_my_active_strategy, register_strategy_to_nest]))

    # Meerkat Scanner: 차트 분석 및 타점 계산
    workflow.add_node("meerkat_scanner", meerkat_node)
    workflow.add_node("meerkat_tools", ToolNode([register_monitoring_targets_to_nest]))

    # 2. 엣지 연결
    workflow.add_edge(START, "owl_director")

    # Owl의 결과에 따른 조건부 분기 (도구 실행, 미어캣 호출, 또는 종료)
    workflow.add_conditional_edges(
        "owl_director", route_after_owl, {"owl_tools": "owl_tools", "meerkat_scanner": "meerkat_scanner", END: END}
    )

    # 도구 실행 후에는 다시 Owl에게 돌아가 결과를 보고하거나 다음 단계를 판단함
    workflow.add_edge("owl_tools", "owl_director")

    # 미어캣 타점 계산 후에는 타점 등록 도구 실행
    workflow.add_edge("meerkat_scanner", "meerkat_tools")
    workflow.add_edge("meerkat_tools", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
