from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agents.meerkat_scanner.meerkat_scanner import meerkat_scanner_node
from agents.owl_director.owl_director import owl_node
from state.magpie_state import MagpieState
from tools.db_tools import register_strategy

load_dotenv()


def owl_router(state: dict) -> str:
    """
    Owl Director의 마지막 메시지를 보고 다음 노드를 결정합니다.

    - request_chart_analysis 툴 호출 → meerkat_scanner 서브 에이전트
    - 그 외 툴 호출 (register_strategy 등) → tools 노드
    - 툴 호출 없음 → END (사용자에게 응답 완료)
    """
    messages = state["messages"]
    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tc in last_message.tool_calls:
            if tc["name"] == "request_chart_analysis":
                return "meerkat_scanner"
        return "tools"

    return END


def build_graph():
    workflow = StateGraph(MagpieState)

    # 노드(Node) 추가
    # A. Owl Director: 전략 기획 및 대화 총괄
    workflow.add_node("owl_director", owl_node)

    # B. Meerkat Scanner: 기술적 지표 계산 및 해석 서브 에이전트
    workflow.add_node("meerkat_scanner", meerkat_scanner_node)

    # C. 일반 도구 실행 노드 (register_strategy 등)
    tools = [register_strategy]
    tool_node = ToolNode(tools)
    workflow.add_node("tools", tool_node)

    # 엣지(Edge) 연결 (흐름 제어)
    workflow.add_edge(START, "owl_director")

    # Owl Director → 커스텀 라우터로 분기
    workflow.add_conditional_edges(
        "owl_director",
        owl_router,
        {
            "meerkat_scanner": "meerkat_scanner",  # 차트 분석 요청 → Meerkat Scanner
            "tools": "tools",  # 일반 도구 → ToolNode
            END: END,  # 응답 완료 → 종료
        },
    )

    # Meerkat Scanner 완료 → Owl Director가 결과 수신하여 사용자에게 전달
    workflow.add_edge("meerkat_scanner", "owl_director")

    # 일반 도구 완료 → Owl Director로 복귀
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
