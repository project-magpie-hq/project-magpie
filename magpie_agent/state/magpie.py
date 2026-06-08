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
    # 매일 오전 9시 정기 검진(DailyReport) 모드 플래그
    is_daily_review: bool | None
    # Owl이 다음 Agent를 누구를 부를지 결정하는 변수
    next_agent: AgentEnum | None
    # 백테스트에서 차트/타점 계산 기준이 되는 과거 시점
    backtest_time: str | None
    # Daemon에서 트리거된 시그널 정보 (어떤 코인, 가격, 사유)
    trigger_info: dict[str, Any] | None

    # 실제 체결/주문 결과(향후 execution tool 연동용)
    execution_result: dict[str, Any] | None

    # Hawk Picker: 1차 선정한 후보 코인 리스트 (Phase 1 → Meerkat 전달용)
    # Meerkat은 이 값이 존재하면 Hawk으로 복귀, 없으면 Calculate Team으로 라우팅
    hawk_candidates: list[str] | None

    # --- Calculate Team (Bull/Bear/Dolphin) 전용 필드 ---

    # Meerkat Scanner가 생성한 차트 분석 결과 (Calculate Team 입력용)
    chart_context: str | None
    # 전략 상세 (JSON string)
    strategy_details: str | None
    # 직전 타점 피드백
    feedback_data: str | None
    # 지갑 정보 (JSON string)
    wallet_data: str | None
    # 최근 매매 기록 (JSON string)
    recent_trades: str | None
    # 기존 타점 정보 (JSON string)
    existing_targets_clean: str | None

    # Bull/Bear/Dolphin 토론 상태
    bull_analysis: str | None
    bear_analysis: str | None
    bull_rebuttal: str | None
    bear_rebuttal: str | None
