import logging

from langgraph.graph import END
from langgraph.prebuilt import ToolNode

from magpie_agent.agents.constant import NodeNames
from magpie_agent.agents.hawk_picker.node import (
    hawk_node,
    route_after_hawk,
    route_after_hawk_tools,
)
from magpie_agent.agents.meerkat_scanner.node import meerkat_node, route_after_meerkat
from magpie_agent.agents.owl_director.node import owl_node, route_after_owl
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

logger = logging.getLogger(__name__)


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
                process_trade_execution,
            ]
        ),
    )
    return workflow


def add_hawk_and_tools(workflow):
    """Add Hawk Picker node and its tool node to the workflow."""
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
    return workflow


def add_meerkat_and_tools(workflow):
    """Add Meerkat Scanner node and its tool node to the workflow."""
    workflow.add_node(NodeNames.MEERKAT_SCANNER.value, meerkat_node)
    workflow.add_node(
        NodeNames.MEERKAT_TOOLS.value,
        ToolNode([register_monitoring_targets_to_nest]),
    )
    return workflow


def add_start_to_owl_edge(workflow):
    """Connect START to Owl Director."""
    workflow.add_edge("__start__", NodeNames.OWL_DIRECTOR.value)
    return workflow


def add_owl_conditional_edges(workflow, owl_routes=None):
    """Add Owl's conditional routing edges.
    
    Default routes: OWL_TOOLS, HAWK_PICKER, MEERKAT_SCANNER, END
    Pass owl_routes to override which destinations are available.
    """
    if owl_routes is None:
        owl_routes = {
            NodeNames.OWL_TOOLS.value: NodeNames.OWL_TOOLS.value,
            NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
            NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
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
            NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
            NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
        }
    workflow.add_conditional_edges(
        NodeNames.OWL_TOOLS.value,
        routing_func,
        owl_tool_routes,
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
    """Add Hawk Tools conditional routing edges."""
    workflow.add_conditional_edges(
        NodeNames.HAWK_TOOLS.value,
        route_after_hawk_tools,
        {
            NodeNames.MEERKAT_SCANNER.value: NodeNames.MEERKAT_SCANNER.value,
            NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
        },
    )
    return workflow


def add_meerkat_conditional_edges(workflow):
    """Add Meerkat Scanner conditional routing edges."""
    workflow.add_conditional_edges(
        NodeNames.MEERKAT_SCANNER.value,
        route_after_meerkat,
        {
            NodeNames.HAWK_PICKER.value: NodeNames.HAWK_PICKER.value,
            NodeNames.MEERKAT_TOOLS.value: NodeNames.MEERKAT_TOOLS.value,
        },
    )
    return workflow


def add_meerkat_tools_to_end(workflow):
    """Connect Meerkat Tools to END."""
    workflow.add_edge(NodeNames.MEERKAT_TOOLS.value, END)
    return workflow
