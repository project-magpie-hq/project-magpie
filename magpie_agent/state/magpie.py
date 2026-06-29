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

    # Fox Finder가 선정한 후보 코인 리스트
    hawk_candidates: list[str] | None

    # --- Per-Coin 병렬 처리 전용 필드 ---
    # Per-Coin Pipeline에서 현재 처리 중인 코인 (단일 코인 처리용)
    current_target_coin: str | None
    # 모든 코인의 병렬 처리 결과를 취합한 리스트
    per_coin_results: list[dict[str, Any]] | None
    # Meerkat이 조회한 현재가 (Calculate Team이 참조)
    current_price: float | None
    # Dolphin이 산출한 코인 신뢰도 점수 (0.0~1.0)
    dolphin_score: float | None
    # Dolphin 판단 근거 요약
    dolphin_reasoning: str | None

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
