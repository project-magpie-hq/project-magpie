from enum import StrEnum
from typing import Any

from langgraph.graph import MessagesState


class AgentEnum(StrEnum):
    MEERKAT = "meerkat_scanner"
    HAWK = "hawk_picker"


class MagpieState(MessagesState):
    """
    Project Magpie의 전체 상태를 관리하는 객체
    MessagesState를 통해 messages: Annotated[list[AnyMessage], add_messages] 상속
    """

    user_id: str
    # Daemon으로부터 불렀는지, 사용자가 불렀는지 구분하는 플래그 변수
    from_daemon: bool
    # Owl이 다음 Agent를 누구를 부를지 결정하는 변수
    next_agent: AgentEnum | None
    # 에이전트가 실행될 특정 시점
    current_sim_time: str | None

    # 실제 체결/주문 결과(향후 execution tool 연동용)
    execution_result: dict[str, Any] | None

    # Hawk Picker: 1차 선정한 후보 코인 리스트 (Phase 1 → Meerkat chart-only 전달용)
    hawk_candidates: list[str] | None
    # Meerkat Scanner: 차트 분석 전용 모드 여부 ("chart_only" or None = 전체 타점 계산)
    meerkat_mode: str | None
