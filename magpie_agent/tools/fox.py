import logging

from langchain_core.tools import tool

from magpie_agent.agents.fox_finder.schema import FoxCandidatesInput

logger = logging.getLogger(__name__)


@tool(args_schema=FoxCandidatesInput)
def store_fox_candidates(target_coins: list[str]) -> str:
    """
    Fox Finder가 1차 선정한 후보 코인 리스트를 등록합니다.
    차트 분석(Meerkat)과 타점 계산(Calculate Team)이 필요한 코인들을 저장할 때 호출하세요.
    최대 20개까지 지정할 수 있습니다.
    """
    print(f"   🦊 [Fox]: 후보 코인 등록 -> {target_coins}")
    return f"후보 코인 {target_coins}이(가) 성공적으로 등록되었습니다."
