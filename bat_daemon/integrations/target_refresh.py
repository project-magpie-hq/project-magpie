import datetime

from magpie_agent.llm import (
    diff_llm_usage_snapshots,
    get_llm_usage_snapshot,
    is_llm_usage_active,
    reset_llm_usage,
    restore_llm_usage,
    save_llm_usage_run,
)


def build_target_refresh_thread_id(user_id: str) -> str:
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
    return f"daemon-refresh:{user_id}:{timestamp}"


def build_target_refresh_inputs(
    user_id: str,
    *,
    target_coin: str | None = None,
    backtest_time: str | None = None,
    prompt_message: str | None = None,
    trigger_info: dict | None = None,
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
        "trigger_info": trigger_info,
    }
    if target_coin:
        inputs["current_target_coin"] = target_coin
    return inputs


async def invoke_graph_for_target_refresh(
    refresh_graph,
    user_id: str,
    *,
    target_coin: str | None = None,
    backtest_time: str | None = None,
    prompt_message: str | None = None,
    trigger_info: dict | None = None,
) -> None:
    print(f"   ♻️ [Daemon->Refresh]: {user_id}의 EXPIRED 타점을 다시 계산하도록 Meerkat 그래프를 호출합니다.")
    if refresh_graph is None:
        raise RuntimeError("refresh_graph is not initialized")

    thread_id = build_target_refresh_thread_id(user_id)
    inputs = build_target_refresh_inputs(
        user_id,
        target_coin=target_coin,
        backtest_time=backtest_time,
        prompt_message=prompt_message,
        trigger_info=trigger_info,
    )
    already_tracking = is_llm_usage_active()
    usage_token = None if already_tracking else reset_llm_usage()
    before_usage = get_llm_usage_snapshot()
    run_type = "backtest-refresh" if backtest_time else "daemon-refresh"
    try:
        await refresh_graph.ainvoke(inputs, config={"configurable": {"thread_id": thread_id}})
    except Exception as exc:
        after_usage = get_llm_usage_snapshot()
        await save_llm_usage_run(
            run_type=run_type,
            graph_name="target_refresh",
            user_id=user_id,
            thread_id=thread_id,
            usage=diff_llm_usage_snapshots(before_usage, after_usage) if already_tracking else after_usage,
            status="failed",
            metadata={
                "target_coin": target_coin,
                "backtest_time": backtest_time,
                "trigger_info": trigger_info,
            },
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        after_usage = get_llm_usage_snapshot()
        await save_llm_usage_run(
            run_type=run_type,
            graph_name="target_refresh",
            user_id=user_id,
            thread_id=thread_id,
            usage=diff_llm_usage_snapshots(before_usage, after_usage) if already_tracking else after_usage,
            metadata={
                "target_coin": target_coin,
                "backtest_time": backtest_time,
                "trigger_info": trigger_info,
            },
        )
    finally:
        if usage_token is not None:
            restore_llm_usage(usage_token)
