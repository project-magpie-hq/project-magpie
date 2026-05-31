import asyncio
from collections.abc import Awaitable

import streamlit as st

_LOOP_KEY = "dashboard_event_loop"


def get_dashboard_event_loop() -> asyncio.AbstractEventLoop:
    loop = st.session_state.get(_LOOP_KEY)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        st.session_state[_LOOP_KEY] = loop
    return loop


def run_async_task[T](awaitable: Awaitable[T]) -> T:
    loop = get_dashboard_event_loop()
    return loop.run_until_complete(awaitable)
