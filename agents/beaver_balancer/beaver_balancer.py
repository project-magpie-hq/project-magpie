import json
import os
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from state.magpie import MagpieState
from tools.portfolio import (
    build_order_availability,
    get_position_for_symbol,
    load_portfolio_snapshot_for_user,
)
from tools.strategy import fetch_active_strategy_for_user

DEFAULT_SYMBOL = "KRW-BTC"
MAX_BUY_RATIO = 0.35
CONCENTRATION_WARNING_RATIO = 0.60


class BeaverChecks(BaseModel):
    has_cash: bool = True
    has_position: bool = False
    position_conflict: bool = False
    portfolio_concentration_warning: bool = False


class BeaverPlanSchema(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"] = "HOLD"
    symbol: str = DEFAULT_SYMBOL
    order_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    order_amount_krw: float = Field(default=0.0, ge=0.0)
    sizing_mode: Literal["cash_ratio", "fixed_amount", "rebalance", "hold"] = "hold"
    reasoning: list[str] = Field(default_factory=list)
    checks: BeaverChecks = Field(default_factory=BeaverChecks)
    next_step_for_owl: Literal["final_decision"] = "final_decision"


def load_prompt() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_beaver_llm() -> Any:
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)
    return llm.with_structured_output(BeaverPlanSchema, method="json_schema")


def _normalize_symbol(raw_symbol: Any) -> str:
    symbol = str(raw_symbol or "").strip().upper()
    if not symbol:
        return DEFAULT_SYMBOL
    if "-" in symbol:
        return symbol
    return f"KRW-{symbol}"


def _extract_trigger_symbol(trigger_event: dict[str, Any] | None, active_strategy: dict[str, Any] | None) -> str:
    if trigger_event:
        for candidate in (
            trigger_event.get("market"),
            trigger_event.get("symbol"),
            (trigger_event.get("trigger_spec") or {}).get("market"),
        ):
            if candidate:
                return _normalize_symbol(candidate)

    strategy_targets = (active_strategy or {}).get("target_coins") or []
    if strategy_targets:
        return _normalize_symbol(strategy_targets[0])
    return DEFAULT_SYMBOL


def _extract_trigger_action(trigger_event: dict[str, Any] | None) -> str:
    action = str((trigger_event or {}).get("signal_type") or (trigger_event or {}).get("action") or "HOLD").upper()
    return action if action in {"BUY", "SELL", "HOLD"} else "HOLD"


def _stringify_reason(reason: Any) -> str:
    text = str(reason or "").strip()
    return text if text else "trigger_event"


def _build_fallback_plan(
    trigger_event: dict[str, Any] | None,
    active_strategy: dict[str, Any] | None,
    portfolio_snapshot: dict[str, Any],
) -> dict[str, Any]:
    symbol = _extract_trigger_symbol(trigger_event, active_strategy)
    trigger_action = _extract_trigger_action(trigger_event)
    reason = _stringify_reason((trigger_event or {}).get("reason"))

    totals = portfolio_snapshot.get("totals", {})
    cash = portfolio_snapshot.get("cash", {})
    portfolio_value = float(totals.get("portfolio_value_krw", 0.0) or 0.0)
    cash_available = float(cash.get("available_krw", 0.0) or 0.0)
    cash_ratio = float(totals.get("cash_ratio", 0.0) or 0.0)

    position = get_position_for_symbol(portfolio_snapshot, symbol)
    position_value = float((position or {}).get("market_value_krw", 0.0) or 0.0)
    position_ratio = float((position or {}).get("allocation_ratio", 0.0) or 0.0)
    target_count = max(len((active_strategy or {}).get("target_coins") or []), 1)

    checks = {
        "has_cash": cash_available > 0,
        "has_position": position_value > 0,
        "position_conflict": False,
        "portfolio_concentration_warning": position_ratio >= CONCENTRATION_WARNING_RATIO,
    }

    if trigger_action == "BUY":
        desired_cash_ratio = min(MAX_BUY_RATIO, max(0.08, round(0.45 / target_count, 4)))
        if cash_available <= 0:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "order_ratio": 0.0,
                "order_amount_krw": 0.0,
                "sizing_mode": "hold",
                "reasoning": [
                    "현재 주문 가능한 예수금이 없어 매수 제안을 보류합니다.",
                    f"트리거 사유는 '{reason}' 이지만 Owl의 재검토가 필요합니다.",
                ],
                "checks": checks,
                "next_step_for_owl": "final_decision",
            }

        order_amount = min(cash_available * desired_cash_ratio, portfolio_value * 0.18 if portfolio_value else cash_available)
        if position_ratio >= CONCENTRATION_WARNING_RATIO:
            order_amount *= 0.5
            checks["portfolio_concentration_warning"] = True

        return {
            "action": "BUY",
            "symbol": symbol,
            "order_ratio": round(min(order_amount / max(cash_available, 1.0), 1.0), 4),
            "order_amount_krw": round(max(order_amount, 0.0), 2),
            "sizing_mode": "cash_ratio",
            "reasoning": [
                f"시장 트리거({reason})와 현재 전략 타깃을 기준으로 {symbol} 매수 후보를 제안합니다.",
                f"현재 현금 비중은 {cash_ratio:.2%}이며 분할 진입 가능한 상태입니다.",
                "최종 체결 전 Owl이 전략 충돌 여부와 실행 타당성을 한 번 더 검토해야 합니다.",
            ],
            "checks": checks,
            "next_step_for_owl": "final_decision",
        }

    if trigger_action == "SELL":
        if position_value <= 0:
            checks["position_conflict"] = True
            return {
                "action": "HOLD",
                "symbol": symbol,
                "order_ratio": 0.0,
                "order_amount_krw": 0.0,
                "sizing_mode": "hold",
                "reasoning": [
                    f"{symbol} 보유 포지션이 없어 매도 대신 보류를 제안합니다.",
                    f"매도 트리거 사유는 '{reason}' 이며 Owl이 최종 판단해야 합니다.",
                ],
                "checks": checks,
                "next_step_for_owl": "final_decision",
            }

        sell_ratio = 1.0 if "STOP" in reason.upper() or "LOSS" in reason.upper() else 0.5
        order_amount = position_value * sell_ratio
        return {
            "action": "SELL",
            "symbol": symbol,
            "order_ratio": round(sell_ratio, 4),
            "order_amount_krw": round(order_amount, 2),
            "sizing_mode": "rebalance" if checks["portfolio_concentration_warning"] else "fixed_amount",
            "reasoning": [
                f"시장 트리거({reason})에 따라 {symbol} 비중 축소/청산 후보를 제안합니다.",
                f"현재 해당 자산 평가금액은 약 {position_value:,.0f} KRW 입니다.",
                "최종 매도 강도와 실행 방식은 Owl이 확정해야 합니다.",
            ],
            "checks": checks,
            "next_step_for_owl": "final_decision",
        }

    return {
        "action": "HOLD",
        "symbol": symbol,
        "order_ratio": 0.0,
        "order_amount_krw": 0.0,
        "sizing_mode": "hold",
        "reasoning": [
            "명확한 매수/매도 트리거가 없어 보류 제안서를 생성했습니다.",
            "Owl이 전략 변경 필요 여부만 점검하면 됩니다.",
        ],
        "checks": checks,
        "next_step_for_owl": "final_decision",
    }


def _apply_soft_guardrails(
    plan: dict[str, Any],
    trigger_event: dict[str, Any] | None,
    active_strategy: dict[str, Any] | None,
    portfolio_snapshot: dict[str, Any],
) -> dict[str, Any]:
    normalized = BeaverPlanSchema(**plan).model_dump()
    symbol = _normalize_symbol(normalized.get("symbol"))
    action = normalized.get("action", "HOLD")

    strategy_targets = {_normalize_symbol(symbol) for symbol in ((active_strategy or {}).get("target_coins") or [])}
    position = get_position_for_symbol(portfolio_snapshot, symbol)
    availability = build_order_availability(portfolio_snapshot, symbol=symbol, side=action)
    cash_available = float(portfolio_snapshot.get("cash", {}).get("available_krw", 0.0) or 0.0)
    position_value = float((position or {}).get("market_value_krw", 0.0) or 0.0)
    position_ratio = float((position or {}).get("allocation_ratio", 0.0) or 0.0)

    reasoning = normalized.get("reasoning") or []
    checks = normalized.get("checks") or {}
    checks["has_cash"] = cash_available > 0
    checks["has_position"] = position_value > 0
    checks["portfolio_concentration_warning"] = position_ratio >= CONCENTRATION_WARNING_RATIO
    checks["position_conflict"] = bool(strategy_targets) and symbol not in strategy_targets

    if action == "BUY":
        if not availability.get("is_orderable"):
            action = "HOLD"
            normalized["order_amount_krw"] = 0.0
            normalized["order_ratio"] = 0.0
            normalized["sizing_mode"] = "hold"
            reasoning.append("예수금이 없어 매수 제안을 HOLD로 완화했습니다.")
        else:
            normalized["order_amount_krw"] = round(min(float(normalized.get("order_amount_krw", 0.0)), cash_available), 2)
            normalized["order_ratio"] = round(
                min(float(normalized.get("order_ratio", 0.0)), MAX_BUY_RATIO, 1.0),
                4,
            )
            if checks["portfolio_concentration_warning"]:
                reasoning.append("기존 비중이 높은 자산이라 과도한 쏠림 경고를 유지합니다.")

    elif action == "SELL":
        if not availability.get("is_orderable"):
            action = "HOLD"
            normalized["order_amount_krw"] = 0.0
            normalized["order_ratio"] = 0.0
            normalized["sizing_mode"] = "hold"
            reasoning.append("매도 가능한 포지션이 없어 SELL 제안을 HOLD로 완화했습니다.")
        else:
            normalized["order_amount_krw"] = round(min(float(normalized.get("order_amount_krw", 0.0)), position_value), 2)
            normalized["order_ratio"] = round(min(float(normalized.get("order_ratio", 0.0)), 1.0), 4)

    if not reasoning:
        reasoning = ["Beaver가 Owl 검토용 기본 제안서를 생성했습니다."]

    normalized["symbol"] = symbol
    normalized["action"] = action
    normalized["reasoning"] = reasoning
    normalized["checks"] = checks
    normalized["next_step_for_owl"] = "final_decision"
    return normalized


async def beaver_node(state: MagpieState) -> dict[str, Any]:
    print("\n🦫 [Beaver]: 포트폴리오를 반영한 분배/매매 제안서를 작성합니다...")

    trigger_event = state.get("trigger_event")
    active_strategy = state.get("active_strategy") or state.get("owl_strategy")
    if not active_strategy:
        active_strategy = await fetch_active_strategy_for_user(state.get("user_id", "default_user"))

    portfolio_snapshot = await load_portfolio_snapshot_for_user(state)
    fallback_plan = _build_fallback_plan(trigger_event, active_strategy, portfolio_snapshot)

    if not trigger_event:
        plan = _apply_soft_guardrails(fallback_plan, trigger_event, active_strategy, portfolio_snapshot)
    else:
        model_input = {
            "trigger_event": trigger_event,
            "active_strategy": active_strategy,
            "portfolio_snapshot": portfolio_snapshot,
        }

        messages = [
            SystemMessage(content=load_prompt()),
            HumanMessage(content=json.dumps(model_input, ensure_ascii=False, indent=2, default=str)),
        ]

        try:
            response = await get_beaver_llm().ainvoke(messages)
            llm_plan = response.model_dump() if isinstance(response, BaseModel) else dict(response)
            plan = _apply_soft_guardrails(llm_plan, trigger_event, active_strategy, portfolio_snapshot)
        except Exception as exc:  # noqa: BLE001
            print(f"   ⚠️ [Beaver]: 구조화 응답 생성 실패. fallback 사용 ({type(exc).__name__})")
            plan = _apply_soft_guardrails(fallback_plan, trigger_event, active_strategy, portfolio_snapshot)

    return {
        "messages": [],
        "trigger_event": trigger_event,
        "active_strategy": active_strategy,
        "owl_strategy": active_strategy,
        "portfolio_snapshot": portfolio_snapshot,
        "beaver_plan": plan,
    }
