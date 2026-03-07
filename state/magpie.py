from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class MagpieState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
