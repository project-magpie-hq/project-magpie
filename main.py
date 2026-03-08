import asyncio

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agents.meerkat_scanner.meerkat_scanner import meerkat_node
from agents.owl_director.owl_director import owl_node, route_after_owl
from state.magpie_state import MagpieState
from tools.monitor_target_tools import register_monitoring_targets_to_nest
from tools.strategy_tools import get_my_active_strategy, register_strategy_to_nest

load_dotenv()


def build_graph():
    workflow = StateGraph(MagpieState)

    workflow.add_node("owl_director", owl_node)
    owl_tools = [get_my_active_strategy, register_strategy_to_nest]
    owl_tool_node = ToolNode(owl_tools)
    workflow.add_node("owl_tools", owl_tool_node)

    workflow.add_node("meerkat_scanner", meerkat_node)
    meerkat_tools = [register_monitoring_targets_to_nest]
    meerkat_tool_node = ToolNode(meerkat_tools)
    workflow.add_node("meerkat_tools", meerkat_tool_node)

    workflow.add_edge(START, "owl_director")
    workflow.add_conditional_edges(
        "owl_director", route_after_owl, {"owl_tools": "owl_tools", "meerkat_scanner": "meerkat_scanner", END: END}
    )
    workflow.add_edge("owl_tools", "owl_director")
    workflow.add_edge("meerkat_scanner", "meerkat_tools")
    workflow.add_edge("meerkat_tools", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


async def main_loop():
    app = build_graph()
    config = {"configurable": {"thread_id": "telegram_chat_001"}}

    print("\n" + "=" * 55)
    print("📱 [Telegram App] - Owl Director 봇과의 대화방 (종료: 'q')")
    print("=" * 55 + "\n")

    while True:
        user_input = input("👤 [나]: ")

        if user_input.lower() in ["q", "quit", "exit"]:
            print("👋 텔레그램 앱을 종료합니다.")
            break

        inputs = {"messages": [("user", user_input)], "user_id": "test_developer_001"}

        async for event in app.astream(inputs, config=config, stream_mode="updates"):
            if "owl_director" in event:
                ai_msg = event["owl_director"]["messages"][0]

                if not ai_msg.tool_calls and ai_msg.content:
                    print(f"\n🦉 [Owl 봇]: {ai_msg.content}\n")


if __name__ == "__main__":
    asyncio.run(main_loop())
