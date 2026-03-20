from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class MagpieState(TypedDict):
    """Project Magpie의 전체 상태를 관리하는 객체"""

    user_id: str
    messages: Annotated[list[BaseMessage], add_messages]

    # 에이전트가 실행될 특정 시점
    current_sim_time: str | None
    # Owl이 결정한 전략 데이터
    owl_strategy: dict | None
    # 전략 갱신 여부 플래그
    is_strategy_updated: bool | None
    # Meerkat이 계산한 타점 데이터
    meerkat_targets: list[dict] | None
