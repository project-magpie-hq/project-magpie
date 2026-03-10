import asyncio

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
    # 타점 등록 완료 후 프로세스 종료
    workflow.add_edge("meerkat_tools", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


async def main_loop():
    """사용자 인터렉션을 처리하는 메인 루프"""
    app = build_graph()
    config = {"configurable": {"thread_id": "telegram_chat_001"}}

    print("\n" + "=" * 55)
    print("📱 [Project Magpie] - Owl Director와의 대화 시작 (종료: 'q')")
    print("=" * 55 + "\n")

    while True:
        try:
            user_input = input("👤 [나]: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["q", "quit", "exit"]:
                print("👋 프로그램을 종료합니다.")
                break

            inputs = {"messages": [("user", user_input)], "user_id": "test_developer_001"}

            # 그래프 실행 (업데이트 스트림 모드)
            async for event in app.astream(inputs, config=config, stream_mode="updates"):
                # Owl의 최종 응답 출력
                if "owl_director" in event:
                    node_output = event["owl_director"]
                    if "messages" in node_output:
                        ai_msg = node_output["messages"][0]
                        # 도구 호출이 아닌 일반 메시지인 경우에만 출력
                        if not getattr(ai_msg, "tool_calls", None) and ai_msg.content:
                            print(f"\n🦉 [Owl]: {ai_msg.content}\n")

                # 미어캣의 활동 표시
                elif "meerkat_scanner" in event:
                    print("🦦 [Meerkat]: 타점 분석을 마치고 결과를 기록했습니다.")

        except KeyboardInterrupt:
            print("\n👋 프로그램을 강제 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ [Error]: {e}")


if __name__ == "__main__":
    asyncio.run(main_loop())
