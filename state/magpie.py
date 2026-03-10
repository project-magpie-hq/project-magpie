from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class MagpieState(TypedDict):
    """Project Magpie의 전체 상태를 관리하는 객체"""

    user_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    # Owl이 결정한 전략 데이터 (Meerkat 전달용)
    owl_strategy: dict | None
    # Meerkat이 계산한 타점 데이터
    meerkat_targets: list[dict] | None
