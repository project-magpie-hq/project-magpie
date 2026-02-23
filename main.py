from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agents.owl_director.owl_director import owl_node
from state.magpie_state import MagpieState
from tools.db_tools import register_strategy

load_dotenv()


def build_graph():
    workflow = StateGraph(MagpieState)

    # 2. 노드(Node) 추가
    # A. owl node
    workflow.add_node("owl_director", owl_node)

    # B. 도구 실행 노드
    tools = [register_strategy]
    tool_node = ToolNode(tools)
    workflow.add_node("tools", tool_node)

    # 3. 엣지(Edge) 연결 (흐름 제어)
    workflow.add_edge(START, "owl_director")
    workflow.add_conditional_edges("owl_director", tools_condition)
    workflow.add_edge("tools", "owl_director")

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


if __name__ == "__main__":
    app = build_graph()
    config = {"configurable": {"thread_id": "telegram_chat_001"}}

    # 사용자가 입력하는 자연어 메시지
    print("\n" + "=" * 55)
    print("📱 [Telegram App] - Owl Director 봇과의 대화방 (종료: 'q')")
    print("=" * 55 + "\n")

    while True:
        # 사용자가 텔레그램에 타이핑하는 것을 시뮬레이션
        user_input = input("👤 [나]: ")

        if user_input.lower() in ["q", "quit", "exit"]:
            print("👋 텔레그램 앱을 종료합니다.")
            break

        inputs = {"messages": [("user", user_input)]}

        for event in app.stream(inputs, config=config, stream_mode="updates"):
            if "owl_director" in event:
                ai_msg = event["owl_director"]["messages"][0]

                # 도구 호출이 아닐 때만 텔레그램 메시지로 전송
                if not ai_msg.tool_calls and ai_msg.content:
                    print(f"\n🦉 [Owl 봇]: {ai_msg.content}\n")
