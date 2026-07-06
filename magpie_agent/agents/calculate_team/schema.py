"""Calculate Team 스키마 정의

Bull(낙관), Bear(비관), Dolphin(중재) 간 토론을 위한 상태 및 스키마.
"""

from langgraph.graph import MessagesState


class CalculateTeamState(MessagesState):
    """Calculate Team 하위 그래프 전용 상태.

    MessagesState를 상속받아 bull/bear/dolphin 노드 간 토론 결과를
    messages에 누적하고, 최종적으로 dolphin이 register_monitoring_targets_to_nest
    도구 호출을 포함한 AIMessage를 생성한다.
    """

    # ---------- 입력 (부모 그래프에서 전달) ----------
    user_id: str
    current_target_coin: str | None = None  # type: ignore[misc]
    strategy_details: str | None = None  # type: ignore[misc]
    chart_context: str | None = None  # type: ignore[misc]
    feedback_data: str | None = None  # type: ignore[misc]
    wallet_data: str | None = None  # type: ignore[misc]
    recent_trades: str | None = None  # type: ignore[misc]
    existing_targets_clean: str | None = None  # type: ignore[misc]
    trigger_info: str | None = None  # type: ignore[misc]
    target_coins: str | None = None  # type: ignore[misc]

    # ---------- 토론 상태 ----------
    bull_analysis: str | None
    bear_analysis: str | None
    bull_rebuttal: str | None
    bear_rebuttal: str | None

    # ---------- Dolphin 평가 ----------
    dolphin_score: float | None = None  # type: ignore[misc]
    dolphin_reasoning: str | None = None  # type: ignore[misc]
