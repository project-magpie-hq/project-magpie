from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class MagpieState(TypedDict):
    user_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    action_type: str
    owl_strategy: dict | None
    meerkat_targets: list[dict] | None
