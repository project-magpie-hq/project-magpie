import streamlit as st


def render_sidebar() -> None:
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
