import asyncio

from dotenv import load_dotenv

from main.graph import build_graph

load_dotenv()


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
