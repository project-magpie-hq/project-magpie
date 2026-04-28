"""
Project Magpie — Streamlit Agent Dashboard

LangGraph 에이전트의 실행 흐름, 도구 호출, MongoDB 작업,
MagpieState 변화를 실시간 스트리밍으로 시각화합니다.

실행: streamlit run dashboard.py
"""

import asyncio
import json
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

load_dotenv()

# ── 노드 메타데이터 ────────────────────────────────────────────────────────────

NODE_OWL_DIRECTOR = "owl_director"
NODE_OWL_TOOLS = "owl_tools"
NODE_MEERKAT_SCANNER = "meerkat_scanner"
NODE_MEERKAT_TOOLS = "meerkat_tools"

NODE_META: dict[str, tuple[str, str, str]] = {
    NODE_OWL_DIRECTOR: ("🦉", "Owl Director", "사용자 의도 분석 및 전략 수립"),
    NODE_OWL_TOOLS: ("🛠️", "Owl Tools", "Owl이 선택한 도구 실행"),
    NODE_MEERKAT_SCANNER: ("🦦", "Meerkat Scanner", "차트 데이터 분석 및 타점 계산"),
    NODE_MEERKAT_TOOLS: ("⚙️", "Meerkat Tools", "Meerkat이 계산한 타점 등록"),
}

# ── MongoDB 도구 메타데이터 ────────────────────────────────────────────────────

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
    "register_monitoring_targets_to_nest": {
        "op": "write",
        "collection": "monitoring_targets",
        "desc": "감시 타점 리스트를 저장합니다 (upsert)",
        "icon": "💾",
    },
}


# ── 유틸리티 ──────────────────────────────────────────────────────────────────


def pretty_json(data: Any) -> str:
    """값을 보기 좋은 JSON 문자열로 변환"""
    try:
        if isinstance(data, str):
            return json.dumps(json.loads(data), ensure_ascii=False, indent=2)
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(data)


def extract_final_owl_response(events: list[dict]) -> str | list[str | dict[Any, Any]] | None:
    """이벤트 목록에서 Owl의 최종 텍스트 응답(tool_call 없는 AIMessage)을 추출"""
    for event in reversed(events):
        if NODE_OWL_DIRECTOR in event:
            messages = event[NODE_OWL_DIRECTOR].get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    return msg.content
    return None


# ── 렌더링 함수 ───────────────────────────────────────────────────────────────


def render_tool_call(tool_call: ToolCall) -> None:
    """도구 호출 정보를 expander로 렌더링"""
    name: str = tool_call.get("name", "unknown")
    # InjectedState는 내부 주입 파라미터이므로 표시 제외
    args: dict = {k: v for k, v in tool_call.get("args", {}).items() if k != "state"}

    # 에이전트 이관 도구
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
    """도구 실행 결과를 expander로 렌더링"""
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
    """LangChain 메시지 객체를 JSON 직렬화 가능한 dict로 변환"""
    if hasattr(msg, "model_dump"):
        raw = msg.model_dump()
    elif hasattr(msg, "dict"):
        raw = msg.dict()
    else:
        raw = {"type": type(msg).__name__, "content": str(msg)}
    # tool_calls 내 id 등 불필요한 내부 필드는 그대로 유지 (원본 그대로 보여주는 것이 목적)
    return raw


def render_node_event(node_name: str, node_output: dict) -> None:
    """
    단일 노드 이벤트를 렌더링합니다.
    st.status() 내부 또는 st.expander() 내부 모두에서 사용 가능합니다.
    """
    icon, label, desc = NODE_META.get(node_name, ("⚙️", node_name, ""))

    st.markdown(f"##### {icon} {label}")
    st.caption(desc)

    messages: list = node_output.get("messages", [])

    # ── Raw messages 전체를 먼저 expander로 표시 ──────────────────────────────
    if messages:
        raw_label = f"📨 messages ({len(messages)}개)"
        with st.expander(raw_label, expanded=False):
            for i, msg in enumerate(messages):
                msg_type = type(msg).__name__
                st.markdown(f"**[{i}] `{msg_type}`**")
                st.code(pretty_json(serialize_message(msg)), language="json")

    has_ai_response = False

    for msg in messages:
        if isinstance(msg, AIMessage):
            # 도구 호출 메시지
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    render_tool_call(tc)
            # 텍스트 응답 (최종 답변)
            # if msg.content:
            #     has_ai_response = True
            #     with st.container(border=True):
            #         st.markdown("**💬 응답:**")
            #         st.markdown(msg.content)

        elif isinstance(msg, ToolMessage):
            render_tool_result(msg)

    if not messages and not has_ai_response:
        st.caption("_이 노드에서 메시지 변경 없음_")


def render_state(accumulated_state: dict) -> None:
    """현재까지 누적된 MagpieState 전체를 렌더링"""
    if not accumulated_state:
        return

    with st.expander("📊 현재 MagpieState", expanded=False):
        messages = accumulated_state.get("messages", [])
        st.markdown(f"**`messages`** — {len(messages)}개")
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__
            if isinstance(msg, AIMessage):
                icon = "🤖"
                if getattr(msg, "tool_calls", None):
                    tc_names = ", ".join(tc["name"] for tc in msg.tool_calls)
                    preview = f"[tool_calls: {tc_names}]"
                else:
                    content_str = str(getattr(msg, "content", ""))
                    preview = content_str[:120] + "..." if len(content_str) > 120 else content_str
            elif isinstance(msg, ToolMessage):
                icon = "🔧"
                content_str = str(msg.content)
                preview = content_str[:120] + "..." if len(content_str) > 120 else content_str
            else:
                icon = "👤"
                content_str = str(getattr(msg, "content", ""))
                preview = content_str[:120] + "..." if len(content_str) > 120 else content_str
            st.markdown(f"`[{i}]` {icon} **{msg_type}** — {preview}")

        other_fields = {k: v for k, v in accumulated_state.items() if k != "messages"}
        for field, value in other_fields.items():
            if value is None:
                st.markdown(f"**`{field}`** — `None`")
            elif isinstance(value, bool):
                badge = "✅ True" if value else "❌ False"
                st.markdown(f"**`{field}`** — {badge}")
            elif isinstance(value, str):
                st.markdown(f"**`{field}`** — `{value}`")
            else:
                st.markdown(f"**`{field}`**")
                st.code(pretty_json(value), language="json")


# ── 세션 상태 초기화 ──────────────────────────────────────────────────────────


def init_session_state() -> None:
    if "app" not in st.session_state:
        from main.graph import build_graph

        with st.spinner("🔧 LangGraph 그래프를 초기화하는 중..."):
            st.session_state.app = build_graph()

    defaults: dict[str, Any] = {
        # 대화 히스토리: list of {user_input, events, final_response}
        "history": [],
        "user_id": "test_developer_001",
        "thread_id": "dashboard_session_001",
    }
    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val


# ── 비동기 스트리밍 실행 ──────────────────────────────────────────────────────


async def astream_and_render(user_input: str, config: dict) -> tuple[list[dict], dict]:
    """
    에이전트를 스트리밍으로 실행합니다.
    각 노드가 완료될 때마다 즉시 st. API를 호출해 UI를 갱신하고,
    (전체 이벤트 목록, 최종 누적 MagpieState)를 반환합니다.
    """
    app = st.session_state.app
    inputs = {
        "messages": [("user", user_input)],
        "user_id": st.session_state.user_id,
        "from_daemon": False,
    }

    collected: list[dict] = []

    # 체크포인트에서 이전 state 로드 → 이전 메시지 히스토리 포함
    try:
        snapshot = app.get_state(config)
        accumulated_state: dict = {k: list(v) if k == "messages" else v for k, v in snapshot.values.items()}
    except Exception:
        accumulated_state = {}

    # 현재 턴의 사용자 입력 추가 (노드 출력에 포함되지 않으므로 직접 추가)
    accumulated_state.setdefault("messages", [])
    accumulated_state["messages"].append(HumanMessage(content=user_input))

    async for event in app.astream(inputs, config=config, stream_mode="updates"):
        collected.append(event)
        for node_name, node_output in event.items():
            # 누적 state 업데이트: messages는 추가, 나머지는 덮어쓰기
            for k, v in node_output.items():
                if k == "messages":
                    accumulated_state.setdefault("messages", [])
                    accumulated_state["messages"].extend(v if isinstance(v, list) else [v])
                else:
                    accumulated_state[k] = v
            render_node_event(node_name, node_output)

    return collected, accumulated_state


# ── 메인 앱 ───────────────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(
        page_title="Magpie Dashboard",
        layout="wide",
    )

    init_session_state()

    # ── 사이드바 ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ 설정")

        new_user_id = st.text_input(
            "User ID",
            value=st.session_state.user_id,
            help="MongoDB strategies / monitoring_targets 조회·저장에 사용되는 사용자 식별자",
        )
        if new_user_id != st.session_state.user_id:
            st.session_state.user_id = new_user_id

        new_thread = st.text_input(
            "Thread ID",
            value=st.session_state.thread_id,
            help="같은 Thread ID를 유지하면 LangGraph MemorySaver가 이전 대화를 기억합니다",
        )
        if new_thread != st.session_state.thread_id:
            st.session_state.thread_id = new_thread

        st.divider()

        st.markdown("**Tools**")
        st.markdown(
            "- `transfer_to_agent` — 다른 에이전트로 제어권 이관\n"
            "- `get_my_active_strategy` — 활성 투자 전략 조회\n"
            "- `register_strategy_to_nest` — 투자 전략 저장 (upsert)\n"
            "- `register_monitoring_targets_to_nest` — 감시 타점 리스트 저장 (upsert)"
        )

        st.divider()

        st.markdown("**MongoDB 컬렉션**")
        st.markdown("- `the_nest.strategies` — 투자 전략\n- `the_nest.monitoring_targets` — 감시 타점")

        st.divider()

        if st.button("🗑️ 대화 기록 초기화", type="secondary", use_container_width=True):
            st.session_state.history = []
            st.rerun()

    # ── 메인 헤더 ─────────────────────────────────────────────────────────────
    st.title("Magpie Dashboard", text_alignment="center")
    st.caption(
        "LangGraph 에이전트 실행 흐름 · 도구 호출 인자 및 결과 · "
        "MongoDB 저장/조회 · MagpieState 변화를 실시간으로 시각화합니다.",
        text_alignment="center",
    )

    # ── 과거 대화 히스토리 렌더링 ─────────────────────────────────────────────
    for i, turn in enumerate(st.session_state.history, start=1):
        with st.chat_message("user"):
            st.write(turn["user_input"])

        with st.expander(f"🔍 Agent 실행 과정 — Turn {i}", expanded=False):
            acc_state: dict = {}
            for event in turn["events"]:
                for node_name, node_output in event.items():
                    for k, v in node_output.items():
                        if k == "messages":
                            acc_state.setdefault("messages", [])
                            acc_state["messages"].extend(v if isinstance(v, list) else [v])
                        else:
                            acc_state[k] = v
                    render_node_event(node_name, node_output)

        if turn.get("final_response"):
            with st.chat_message("assistant"):
                st.write(turn["final_response"])

        st.divider()

    # ── 사용자 입력 ───────────────────────────────────────────────────────────
    user_input = st.chat_input("Owl Director에게 메시지를 보내세요...")

    if user_input:
        config = {"configurable": {"thread_id": st.session_state.thread_id}}

        # 사용자 메시지 즉시 표시
        with st.chat_message("user"):
            st.write(user_input)

        events: list[dict] = []
        final_state: dict = {}

        # 스트리밍 실행 — st.status()가 실시간으로 내용을 업데이트함
        with st.status("🤖 에이전트 실행 중...", expanded=True) as status:
            try:
                events, final_state = asyncio.run(astream_and_render(user_input, config))
                status.update(
                    label="✅ 실행 완료",
                    state="complete",
                    expanded=False,
                )
            except Exception as exc:
                st.exception(exc)
                status.update(label="❌ 오류 발생", state="error")

        render_state(final_state)

        # 최종 Owl 텍스트 응답 추출 및 표시
        final_response = extract_final_owl_response(events)

        if final_response:
            with st.chat_message("assistant"):
                st.write(final_response)

        # 히스토리에 저장 (다음 렌더링 시 과거 대화로 표시됨)
        st.session_state.history.append(
            {
                "user_input": user_input,
                "events": events,
                "final_response": final_response,
            }
        )


if __name__ == "__main__":
    main()
