import datetime


def build_target_refresh_thread_id(user_id: str) -> str:
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
    return f"daemon-refresh:{user_id}:{timestamp}"


def build_target_refresh_inputs(
    user_id: str,
    *,
    backtest_time: str | None = None,
    prompt_message: str | None = None,
) -> dict:
    inputs = {
        "user_id": user_id,
        "messages": [
            (
                "user",
                prompt_message
                or "EXPIRED 상태의 monitoring target이 있습니다. 현재 전략, 지갑, 기존 타점을 참고해 "
                "새로운 waiting-buy 타점을 다시 계산하고 저장하세요.",
            )
        ],
        "from_daemon": True,
        "backtest_time": backtest_time,
    }
    return inputs


async def invoke_graph_for_target_refresh(
    refresh_graph,
    user_id: str,
    *,
    backtest_time: str | None = None,
    prompt_message: str | None = None,
) -> None:
    print(f"   ♻️ [Daemon->Refresh]: {user_id}의 EXPIRED 타점을 다시 계산하도록 Meerkat 그래프를 호출합니다.")
    if refresh_graph is None:
        raise RuntimeError("refresh_graph is not initialized")

    thread_id = build_target_refresh_thread_id(user_id)
    inputs = build_target_refresh_inputs(
        user_id,
        backtest_time=backtest_time,
        prompt_message=prompt_message,
    )
    await refresh_graph.ainvoke(inputs, config={"configurable": {"thread_id": thread_id}})
