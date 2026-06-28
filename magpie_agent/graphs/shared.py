import logging

from langgraph.graph import END
from langgraph.prebuilt import ToolNode

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.fox_finder.node import fox_node
from magpie_agent.agents.hawk_picker.node import (
    hawk_node,
    route_after_hawk,
    route_after_hawk_tools,
)
from magpie_agent.agents.owl_director.node import owl_node, route_after_owl
from magpie_agent.state.magpie import MagpieState
from magpie_agent.tools.fox import store_fox_candidates
from magpie_agent.tools.router import transfer_to_agent
from magpie_agent.tools.strategy import (
    get_my_active_strategy,
    register_strategy_to_nest,
    update_strategy_target_coins,
)
from magpie_agent.tools.wallet import get_wallet

logger = logging.getLogger(__name__)


# =========================================================================
# Owl Director
# =========================================================================


def add_owl_and_tools(workflow, state_cls=MagpieState):
    """Add Owl Director node and its tool node to the workflow."""
    workflow.add_node(NodeNames.OWL_DIRECTOR.value, owl_node)
    workflow.add_node(
        NodeNames.OWL_TOOLS.value,
        ToolNode(
            [
                register_strategy_to_nest,
                get_my_active_strategy,
                transfer_to_agent,
                get_wallet,
            ]
        ),
    )
    return workflow


def add_start_to_owl_edge(workflow):
    """Connect START to Owl Director."""
    workflow.add_edge("__start__", NodeNames.OWL_DIRECTOR.value)
    return workflow


def add_owl_conditional_edges(workflow, owl_routes=None):
    """Add Owl's conditional routing edges.

    Default routes: OWL_TOOLS, FOX_FINDER, HAWK_PICKER, END
    Pass owl_routes to override which destinations are available.
    """
    if owl_routes is None:
        owl_routes = {
            NodeNames.OWL_TOOLS.value: NodeNames.OWL_TOOLS.value,
            NodeNames.FOX_FINDER.value: NodeNames.FOX_FINDER.value,
            NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
            END: END,
        }
    workflow.add_conditional_edges(
        NodeNames.OWL_DIRECTOR.value,
        route_after_owl,
        owl_routes,
    )
    return workflow


def add_owl_tools_conditional_edges(workflow, routing_func, owl_tool_routes=None):
    """Add Owl Tools' conditional routing edges."""
    if owl_tool_routes is None:
        owl_tool_routes = {
            NodeNames.OWL_DIRECTOR.value: NodeNames.OWL_DIRECTOR.value,
            NodeNames.FOX_FINDER.value: NodeNames.FOX_FINDER.value,
        }
    workflow.add_conditional_edges(
        NodeNames.OWL_TOOLS.value,
        routing_func,
        owl_tool_routes,
    )
    return workflow


# =========================================================================
# Fox Finder (후보 종목 선정 — Hawk Phase 1 대체)
# =========================================================================


def add_fox_and_tools(workflow):
    """Add Fox Finder node and its tool node to the workflow."""
    workflow.add_node(NodeNames.FOX_FINDER.value, fox_node)
    workflow.add_node(
        NodeNames.FOX_TOOLS.value,
        ToolNode([store_fox_candidates]),
    )
    return workflow


def add_fox_conditional_edges(workflow):
    """Add Fox Finder conditional routing edges: Fox → Fox Tools or END."""
    from magpie_agent.agents.fox_finder.node import route_after_fox

    workflow.add_conditional_edges(
        NodeNames.FOX_FINDER.value,
        route_after_fox,
        {
            NodeNames.FOX_TOOLS.value: NodeNames.FOX_TOOLS.value,
            END: END,
        },
    )
    return workflow


def add_fox_tools_to_subgraph(workflow):
    """Connect Fox Tools to Analyze & Calculate subgraph."""
    workflow.add_edge(NodeNames.FOX_TOOLS.value, NodeNames.ANALYZE_AND_CALCULATE.value)
    return workflow


# =========================================================================
# Analyze & Calculate 서브그래프 (Meerkat → Calculate Team)
# =========================================================================


def add_analyze_and_calculate_subgraph(workflow):
    """Add Analyze & Calculate (Meerkat → Calculate Team) subgraph as a single node."""
    from magpie_agent.graphs.analyze_and_calculate import build_analyze_and_calculate_subgraph

    subgraph = build_analyze_and_calculate_subgraph()
    workflow.add_node(NodeNames.ANALYZE_AND_CALCULATE.value, subgraph)
    return workflow


def add_subgraph_to_hawk(workflow):
    """Connect Analyze & Calculate subgraph to Hawk Picker (최종 선정)."""
    workflow.add_edge(NodeNames.ANALYZE_AND_CALCULATE.value, NodeNames.HAWK_PICKER.value)
    return workflow


# =========================================================================
# Hawk Picker (최종 종목 선정 — Phase 2 only)
# =========================================================================


def add_hawk_and_tools(workflow):
    """Add Hawk Picker node and its tool node to the workflow.

    Hawk는 이제 Phase 2(최종 선정)만 담당하며,
    Fox → Analyze & Calculate 서브그래프 이후에 실행된다.
    """
    workflow.add_node(NodeNames.HAWK_PICKER.value, hawk_node)
    workflow.add_node(
        NodeNames.HAWK_TOOLS.value,
        ToolNode([update_strategy_target_coins]),
    )
    return workflow


def add_hawk_conditional_edges(workflow):
    """Add Hawk Picker conditional routing edges."""
    workflow.add_conditional_edges(
        NodeNames.HAWK_PICKER.value,
        route_after_hawk,
        {
            NodeNames.HAWK_TOOLS.value: NodeNames.HAWK_TOOLS.value,
            END: END,
        },
    )
    return workflow


def add_hawk_tools_conditional_edges(workflow):
    """Add Hawk Tools conditional routing edges: 최종 선정 후 종료."""
    workflow.add_conditional_edges(
        NodeNames.HAWK_TOOLS.value,
        route_after_hawk_tools,
        {
            END: END,
        },
    )
    return workflow
