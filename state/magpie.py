from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class MagpieState(TypedDict, total=False):
    """Project Magpie의 전체 상태를 관리하는 객체"""

    user_id: str
    messages: Annotated[list[BaseMessage], add_messages]

    # 에이전트가 실행될 특정 시점
    current_sim_time: str | None
    # Bat/외부 트리거가 전달한 구조화 이벤트
    trigger_event: dict[str, Any] | None
    # 현재 활성 전략 데이터(신규 표준 필드)
    active_strategy: dict[str, Any] | None
    # 현재 포트폴리오/예수금/포지션 스냅샷
    portfolio_snapshot: dict[str, Any] | None
    # Beaver가 만든 분배 + 매매 제안서(JSON)
    beaver_plan: dict[str, Any] | None
    # Owl의 최종 판단 요약
    owl_decision: dict[str, Any] | None
    # 실제 체결/주문 결과(향후 execution tool 연동용)
    execution_result: dict[str, Any] | None
    # Owl이 결정한 전략 데이터(기존 호환 필드)
    owl_strategy: dict | None
    # 전략 갱신 여부 플래그
    is_strategy_updated: bool | None
    # Meerkat이 계산한 타점 데이터
    meerkat_targets: list[dict] | None
