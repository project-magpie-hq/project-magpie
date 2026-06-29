import json
from typing import Any

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

from dashboard.asyncio_utils import run_async_task
from dashboard.common import pretty_json

NODE_OWL_DIRECTOR = "owl_director"
NODE_OWL_TOOLS = "owl_tools"
NODE_FOX_FINDER = "fox_finder"
NODE_FOX_TOOLS = "fox_tools"
NODE_PARALLEL_COORDINATOR = "parallel_coordinator"
NODE_HAWK_PICKER = "hawk_picker"
NODE_HAWK_TOOLS = "hawk_tools"
NODE_MEERKAT_SCANNER = "meerkat_scanner"
NODE_CALCULATE_TEAM_TOOLS = "calculate_team_tools"

NODE_META: dict[str, tuple[str, str, str]] = {
    NODE_OWL_DIRECTOR: ("🦉", "Owl Director", "사용자 의도 분석 및 전략 수립"),
    NODE_OWL_TOOLS: ("🛠️", "Owl Tools", "Owl이 선택한 도구 실행"),
    NODE_FOX_FINDER: ("🦊", "Fox Finder", "전략 기반 후보 코인 선정"),
    NODE_FOX_TOOLS: ("🔧", "Fox Tools", "Fox가 선정한 후보 코인 저장"),
    NODE_PARALLEL_COORDINATOR: ("⚡", "Parallel Coordinator", "Per-Coin 병렬 분석 실행"),
    NODE_HAWK_PICKER: ("🦅", "Hawk Picker", "Per-Coin 분석 결과 기반 최종 종목 선정"),
    NODE_HAWK_TOOLS: ("🔧", "Hawk Tools", "Hawk이 선정한 코인 등록/전략 업데이트"),
    NODE_MEERKAT_SCANNER: ("🦦", "Meerkat Scanner", "차트 데이터 분석 및 타점 계산"),
    NODE_CALCULATE_TEAM_TOOLS: ("⚙️", "Calculate Team Tools", "Calculate Team이 생성한 타점 등록"),
}

MONGO_TOOL_META: dict[str, dict[str, str]] = {
    "get_my_active_strategy": {
        "op": "read",
        "collection": "strategies",
        "desc": "활성 투자 전략을 조회합니다",
        "icon": "📖",
    },
    "register_strategy_to_nest": {
        "op": "write",
        "collection": "strategies",
        "desc": "투자 전략을 저장합니다 (upsert)",
        "icon": "💾",
    },
    "update_strategy_target_coins": {
        "op": "write",
        "collection": "strategies",
        "desc": "Hawk Picker가 최종 선정한 타겟 코인으로 전략을 업데이트합니다",
        "icon": "🎯",
    },
    "register_monitoring_targets_to_nest": {
        "op": "write",
        "collection": "monitoring_targets",
        "desc": "감시 타점 리스트를 저장합니다 (upsert)",
        "icon": "💾",
    },
}


def extract_final_owl_response(events: list[dict]) -> str | list[str | dict[Any, Any]] | None:
    for event in reversed(events):
        if NODE_OWL_DIRECTOR in event:
            messages = event[NODE_OWL_DIRECTOR].get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    return msg.content
    return None


def render_tool_call(tool_call: ToolCall) -> None:
    name: str = tool_call.get("name", "unknown")
    args: dict = {k: v for k, v in tool_call.get("args", {}).items() if k != "state"}

    if name == "transfer_to_agent":
        next_agent = args.get("next_agent", "unknown")
        with st.expander(f"🔀 Agent 이관 | `{name}` → `{next_agent}`", expanded=True):
            st.info(f"제어권을 **{next_agent}** 에이전트로 이관합니다.")
        return

    mongo = MONGO_TOOL_META.get(name)
    if mongo:
        op_badge = "📖 DB 조회" if mongo["op"] == "read" else "💾 DB 저장"
        title = f"{op_badge} | `{name}` → `the_nest.{mongo['collection']}`"
    else:
        title = f"🔧 Tool 호출 | `{name}`"

    with st.expander(title, expanded=True):
        if mongo:
            st.caption(f"MongoDB `the_nest.{mongo['collection']}` — {mongo['desc']}")

        if args:
            st.markdown("**입력 파라미터:**")
            st.code(pretty_json(args), language="json")
        elif mongo and mongo["op"] == "read":
            st.caption("_state에서 user_id를 주입받아 조회 (별도 파라미터 없음)_")


def render_tool_result(msg: ToolMessage) -> None:
    name: str = msg.name or "unknown"
    content = msg.content
    mongo = MONGO_TOOL_META.get(name)

    if mongo:
        op_badge = "✅ 조회 결과" if mongo["op"] == "read" else "✅ 저장 완료"
        title = f"{op_badge} | `{name}` ← `the_nest.{mongo['collection']}`"
    else:
        title = f"✅ Tool 결과 | `{name}`"

    with st.expander(title, expanded=True):
        if isinstance(content, (dict, list)):
            st.code(pretty_json(content), language="json")
        elif isinstance(content, str):
            try:
                parsed = json.loads(content)
                st.code(pretty_json(parsed), language="json")
            except (json.JSONDecodeError, ValueError):
                if "성공" in content or "완료" in content:
                    st.success(content)
                else:
                    st.write(content)
        else:
            st.write(str(content))


def serialize_message(msg: Any) -> dict:
    if hasattr(msg, "model_dump"):
        return msg.model_dump()
    if hasattr(msg, "dict"):
        return msg.dict()
    return {"type": type(msg).__name__, "content": str(msg)}


def render_node_event(node_name: str, node_output: dict) -> None:
    icon, label, desc = NODE_META.get(node_name, ("⚙️", node_name, ""))

    st.markdown(f"##### {icon} {label}")
    st.caption(desc)

    messages: list = node_output.get("messages", [])
    if messages:
        with st.expander(f"📨 messages ({len(messages)}개)", expanded=False):
            for i, msg in enumerate(messages):
                st.markdown(f"**[{i}] `{type(msg).__name__}`**")
                st.code(pretty_json(serialize_message(msg)), language="json")

    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tool_call in msg.tool_calls:
                render_tool_call(tool_call)
        elif isinstance(msg, ToolMessage):
            render_tool_result(msg)

    if not messages:
        st.caption("_이 노드에서 메시지 변경 없음_")


def render_state(accumulated_state: dict) -> None:
    if not accumulated_state:
        return

    with st.expander("📊 현재 MagpieState", expanded=False):
        messages = accumulated_state.get("messages", [])
        st.markdown(f"**`messages`** — {len(messages)}개")
        for i, msg in enumerate(messages):
            st.markdown(f"`[{i}]` {message_preview(msg)}")

        for field, value in accumulated_state.items():
            if field == "messages":
                continue
            st.markdown(f"**`{field}`**")
            if isinstance(value, str):
                st.markdown(f"`{value}`")
            elif value is None:
                st.markdown("`None`")
            else:
                st.code(pretty_json(value), language="json")


def message_preview(msg: Any) -> str:
    msg_type = type(msg).__name__
    if isinstance(msg, AIMessage):
        icon = "🤖"
        if getattr(msg, "tool_calls", None):
            preview = f"[tool_calls: {', '.join(tc['name'] for tc in msg.tool_calls)}]"
        else:
            content = str(getattr(msg, "content", ""))
            preview = content[:120] + "..." if len(content) > 120 else content
    elif isinstance(msg, ToolMessage):
        icon = "🔧"
        content = str(msg.content)
        preview = content[:120] + "..." if len(content) > 120 else content
    else:
        icon = "👤"
        content = str(getattr(msg, "content", ""))
        preview = content[:120] + "..." if len(content) > 120 else content
    return f"{icon} **{msg_type}** — {preview}"


async def astream_and_render(user_input: str, config: dict) -> tuple[list[dict], dict]:
    app = st.session_state.app
    inputs = {
        "messages": [("user", user_input)],
        "user_id": st.session_state.user_id,
        "from_daemon": False,
    }

    collected: list[dict] = []
    try:
        snapshot = app.get_state(config)
        accumulated_state: dict = {k: list(v) if k == "messages" else v for k, v in snapshot.values.items()}
    except Exception:
        accumulated_state = {}

    accumulated_state.setdefault("messages", [])
    accumulated_state["messages"].append(HumanMessage(content=user_input))

    async for event in app.astream(inputs, config=config, stream_mode="updates"):
        collected.append(event)
        for node_name, node_output in event.items():
            update_accumulated_state(accumulated_state, node_output)
            render_node_event(node_name, node_output)

    return collected, accumulated_state


def update_accumulated_state(accumulated_state: dict, node_output: dict) -> None:
    for key, value in node_output.items():
        if key == "messages":
            accumulated_state.setdefault("messages", [])
            accumulated_state["messages"].extend(value if isinstance(value, list) else [value])
        else:
            accumulated_state[key] = value


def render_agent_history() -> None:
    for i, turn in enumerate(st.session_state.history, start=1):
        with st.chat_message("user"):
            st.write(turn["user_input"])

        with st.expander(f"🔍 Agent 실행 과정 — Turn {i}", expanded=False):
            for event in turn["events"]:
                for node_name, node_output in event.items():
                    render_node_event(node_name, node_output)

        if turn.get("final_response"):
            with st.chat_message("assistant"):
                st.write(turn["final_response"])

        st.divider()


def render_agent_controls() -> None:
    st.markdown("#### 실행 설정")
    st.caption("Magpie Agent 실행에 필요한 사용자 식별자와 thread를 이 탭에서 직접 설정합니다.")

    col_a, col_b, col_c = st.columns([1.15, 1.15, 0.7])
    new_user_id = col_a.text_input(
        "User ID",
        value=st.session_state.user_id,
        help="strategies / wallets / monitoring_targets 조회 및 저장에 사용됩니다.",
    )
    new_thread_id = col_b.text_input(
        "Thread ID",
        value=st.session_state.thread_id,
        help="같은 값을 유지하면 LangGraph MemorySaver가 대화 맥락을 이어갑니다.",
    )
    if col_c.button("대화 기록 초기화", type="secondary", width="stretch"):
        st.session_state.history = []
        st.rerun()

    if new_user_id != st.session_state.user_id:
        st.session_state.user_id = new_user_id
    if new_thread_id != st.session_state.thread_id:
        st.session_state.thread_id = new_thread_id


def submit_agent_message() -> None:
    user_input = st.session_state.get("agent_chat_input", "").strip()
    if user_input:
        st.session_state.agent_pending_input = user_input


def render_agent_dashboard() -> None:
    render_agent_controls()
    render_agent_history()

    user_input = st.session_state.pop("agent_pending_input", None)
    if user_input:
        config = {"configurable": {"thread_id": st.session_state.thread_id}}

        with st.chat_message("user"):
            st.write(user_input)

        events: list[dict] = []
        final_state: dict = {}

        with st.status("🤖 에이전트 실행 중...", expanded=True) as status:
            try:
                events, final_state = run_async_task(astream_and_render(user_input, config))
                status.update(label="✅ 실행 완료", state="complete", expanded=False)
            except Exception as exc:
                st.exception(exc)
                status.update(label="❌ 오류 발생", state="error")

        render_state(final_state)
        final_response = extract_final_owl_response(events)

        if final_response:
            with st.chat_message("assistant"):
                st.write(final_response)

        st.session_state.history.append(
            {
                "user_input": user_input,
                "events": events,
                "final_response": final_response,
            }
        )

    st.chat_input(
        "Owl Director에게 메시지를 보내세요...",
        key="agent_chat_input",
        on_submit=submit_agent_message,
    )
