from langchain_core.tools import tool

from agents.owl_director.schema import RouterToolInput


@tool(args_schema=RouterToolInput)
def transfer_to_agent(next_agent: str):
    """
    작업을 완료했거나, 다른 전문 에이전트의 도움이 필요할 때 이 도구를 호출하여 제어권을 넘깁니다.
    """
    pass
