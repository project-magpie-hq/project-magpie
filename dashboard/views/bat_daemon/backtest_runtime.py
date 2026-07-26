import threading
import traceback
from queue import Empty, Queue
from typing import Any

import streamlit as st

from bat_daemon.backtest import build_backtest_result, collect_backtest_run
from bat_daemon.utils.backtest import DEFAULT_BACKTEST_REPLAY_MODE
from dashboard.asyncio_utils import run_async_task
from magpie_agent.tools.strategy import fetch_strategy_by_user

MAX_PROCESS_EVENTS = 4000
DEFAULT_REPORT_TICK_ROWS = 10000


def ensure_backtest_stream_state(namespace: str) -> None:
    defaults = {
        f"{namespace}_process_events": [],
        f"{namespace}_backtest_running": False,
        f"{namespace}_backtest_event_queue": None,
        f"{namespace}_backtest_thread": None,
        f"{namespace}_last_report_paths": None,
        f"{namespace}_strategy_cache_user_id": None,
        f"{namespace}_strategy_cache": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def normalize_backtest_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("event_type", "unknown"))
    signal_type = event.get("signal_type")
    if hasattr(signal_type, "value"):
        signal_type = signal_type.value

    expired_coins = event.get("expired_target_coins") or []
    active_coins = event.get("active_coins") or []
    coin = event.get("coin") or event.get("target_coin")
    price = event.get("price")
    raw_time = event.get("event_time") or event.get("candle_time") or event.get("recorded_at")
    category, label = {
        "setup_started": ("setup", "환경 준비 시작"),
        "wallet_initialized": ("setup", "지갑 초기화"),
        "strategy_cloned": ("setup", "전략 복제"),
        "targets_cleared": ("setup", "기존 타점 정리"),
        "initial_refresh_started": ("agent", "초기 타점 계산 시작"),
        "initial_refresh_completed": ("agent", "초기 타점 계산 완료"),
        "initial_targets_loaded": ("setup", "초기 타점 로드"),
        "historical_data_loaded": ("data", "과거 캔들 로드 완료"),
        "historical_coin_started": ("data", "코인 캔들 로드 시작"),
        "historical_coin_progress": ("data", "코인 캔들 로드 중"),
        "historical_coin_loaded": ("data", "코인 캔들 로드 완료"),
        "replay_started": ("run", "tick 재생 시작"),
        "candle_started": ("tick", "캔들 재생"),
        "tick": ("tick", "tick 수신"),
        "tick_processed": ("tick", "tick 처리"),
        "signal": ("signal", "신호 감지"),
        "trade_executed": ("trade", "체결 반영"),
        "target_status_changed": ("target", "타점 상태 변경"),
        "refresh_scheduled": ("agent", "refresh 예약"),
        "refresh_started": ("agent", "refresh 시작"),
        "refresh_completed": ("agent", "refresh 완료"),
        "refresh_failed": ("error", "refresh 실패"),
        "worker_failed": ("error", "worker 실패"),
        "replay_completed": ("done", "tick 재생 완료"),
    }.get(event_type, ("misc", event_type))

    if event_type == "tick_processed":
        message = (
            f"{coin} {price:,.0f}원 처리 ({event.get('processed_ticks', 0):,}/{event.get('total_ticks', 0):,})"
            if isinstance(price, (int, float))
            else f"{coin} tick 처리"
        )
    elif event_type == "signal":
        message = f"{coin} {signal_type} 신호 감지 ({event.get('event_reason')})"
    elif event_type == "trade_executed":
        message = (
            f"{event.get('target_coin')} {signal_type} 체결 "
            f"/ 상태 {event.get('result_status')} / 수량 {event.get('executed_volume')}"
        )
    elif event_type == "refresh_started":
        message = f"EXPIRED 타점 refresh 시작: {', '.join(expired_coins)}"
    elif event_type == "refresh_completed":
        message = f"새 monitoring_target 반영 완료: {', '.join(event.get('active_targets') or [])}"
    elif event_type == "target_status_changed":
        message = f"{event.get('target_coin')} 상태 {event.get('from_status')} -> {event.get('to_status')}"
    elif event_type == "candle_started":
        message = f"{raw_time} 캔들 재생 시작 ({', '.join(active_coins)})"
    else:
        message = str(event.get("message") or label)

    return {
        "time": raw_time,
        "recorded_at": event.get("recorded_at"),
        "category": category,
        "is_system_event": event_type
        in {
            "setup_started",
            "wallet_initialized",
            "strategy_cloned",
            "targets_cleared",
            "initial_refresh_started",
            "initial_refresh_completed",
            "initial_targets_loaded",
            "historical_coin_started",
            "historical_coin_progress",
            "historical_coin_loaded",
            "historical_data_loaded",
            "replay_started",
        },
        "label": label,
        "coin": coin,
        "signal": signal_type,
        "price": price,
        "status": event.get("result_status") or event.get("to_status") or event.get("target_status"),
        "progress": (
            f"{event.get('processed_ticks', 0):,}/{event.get('total_ticks', 0):,}"
            if event_type == "tick_processed"
            else None
        ),
        "message": message,
        "tick_row": event.get("tick_row"),
        "raw": event,
    }


def drain_backtest_event_queue(namespace: str) -> None:
    event_queue = st.session_state.get(f"{namespace}_backtest_event_queue")
    if event_queue is None:
        return

    while True:
        try:
            payload = event_queue.get_nowait()
        except Empty:
            break

        kind = payload.get("kind")
        if kind == "event":
            process_events = st.session_state[f"{namespace}_process_events"]
            process_events.append(normalize_backtest_event(payload["event"]))
            if len(process_events) > MAX_PROCESS_EVENTS:
                st.session_state[f"{namespace}_process_events"] = process_events[-MAX_PROCESS_EVENTS:]
        elif kind == "result":
            st.session_state.bat_backtest_result = payload["result"]
        elif kind == "done":
            st.session_state[f"{namespace}_backtest_running"] = False
            st.session_state[f"{namespace}_backtest_thread"] = None
            st.session_state[f"{namespace}_backtest_event_queue"] = None


def start_backtest_worker(
    namespace: str,
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    end: str,
    initial_balance: float,
    selected_target_coins: list[str] | None,
    replay_mode: str = DEFAULT_BACKTEST_REPLAY_MODE,
) -> None:
    event_queue: Queue[dict[str, Any]] = Queue()

    def progress_callback(event: dict[str, Any]) -> None:
        event_queue.put({"kind": "event", "event": event})

    def worker() -> None:
        try:
            result = run_async_task(
                collect_backtest_run(
                    strategy_user_id,
                    backtest_id,
                    start,
                    end,
                    float(initial_balance),
                    selected_target_coins=selected_target_coins,
                    replay_mode=replay_mode,
                    max_tick_rows=DEFAULT_REPORT_TICK_ROWS,
                    progress_callback=progress_callback,
                )
            )
        except Exception as exc:  # noqa: BLE001
            progress_callback(
                {
                    "event_type": "worker_failed",
                    "message": f"백테스트 worker가 예외로 종료되었습니다: {type(exc).__name__}: {exc}",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            result = build_backtest_result({}, {}, str(exc))
        event_queue.put({"kind": "result", "result": result})
        event_queue.put({"kind": "done"})

    st.session_state[f"{namespace}_process_events"] = []
    st.session_state.bat_backtest_result = None
    st.session_state[f"{namespace}_last_report_paths"] = None
    st.session_state.pop(f"{namespace}_result_plot_coin", None)
    st.session_state.pop(f"{namespace}_result_plot_coin_widget", None)
    st.session_state[f"{namespace}_backtest_event_queue"] = event_queue
    st.session_state[f"{namespace}_backtest_running"] = True
    thread = threading.Thread(target=worker, daemon=True)
    st.session_state[f"{namespace}_backtest_thread"] = thread
    thread.start()


def load_cached_strategy(namespace: str, strategy_user_id: str) -> dict[str, Any] | None:
    normalized_user_id = strategy_user_id.strip()
    cache_user_id_key = f"{namespace}_strategy_cache_user_id"
    cache_value_key = f"{namespace}_strategy_cache"

    if not normalized_user_id:
        st.session_state[cache_user_id_key] = None
        st.session_state[cache_value_key] = None
        return None

    if st.session_state.get(cache_user_id_key) == normalized_user_id:
        return st.session_state.get(cache_value_key)

    source_strategy = run_async_task(fetch_strategy_by_user(normalized_user_id))
    st.session_state[cache_user_id_key] = normalized_user_id
    st.session_state[cache_value_key] = source_strategy
    return source_strategy
