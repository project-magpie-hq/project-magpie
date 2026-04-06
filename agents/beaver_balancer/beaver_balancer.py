import json
import os
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from state.magpie import MagpieState
from tools.portfolio import build_order_availability, get_position_for_symbol, load_portfolio_snapshot_for_user
from tools.strategy import fetch_active_strategy_for_user

DEFAULT_SYMBOL = "KRW-BTC"
MIN_ACTION_AMOUNT_KRW = 50_000.0
MAX_SINGLE_ACTION_CASH_SHARE = 0.20
MAX_TOTAL_BUY_CASH_SHARE = 0.35
CONCENTRATION_WARNING_RATIO = 0.60
OVERWEIGHT_REBALANCE_BUFFER = 0.12


class BeaverActionChecks(BaseModel):
    has_cash: bool = True
    has_position: bool = False
    position_conflict: bool = False
    portfolio_concentration_warning: bool = False


class BeaverPlanActionSchema(BaseModel):
    symbol: str = DEFAULT_SYMBOL
    action: Literal["BUY", "SELL", "HOLD"] = "HOLD"
    order_amount_krw: float = Field(default=0.0, ge=0.0)
    sizing_mode: Literal["fixed_amount", "rebalance", "liquidation", "hold"] = "hold"
    current_allocation_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    target_allocation_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning: list[str] = Field(default_factory=list)
    checks: BeaverActionChecks = Field(default_factory=BeaverActionChecks)


class BeaverPlanSchema(BaseModel):
    summary_action: Literal["BUY", "SELL", "REBALANCE", "HOLD"] = "HOLD"
    actions: list[BeaverPlanActionSchema] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    next_step_for_owl: Literal["final_decision"] = "final_decision"


def load_prompt() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_beaver_llm() -> Any:
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)
    return llm.with_structured_output(BeaverPlanSchema, method="json_schema")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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
            trigger_event.get("target_coin"),
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
    if not trigger_event:
        return "HOLD"

    action = str(trigger_event.get("signal_type") or trigger_event.get("action") or "").strip().upper()
    if action in {"BUY", "SELL", "HOLD"}:
        return action

    reason = _stringify_reason(trigger_event).upper()
    if any(token in reason for token in ("STOP", "LOSS", "PROFIT", "TAKE_PROFIT", "SELL")):
        return "SELL"
    if any(token in reason for token in ("BUY", "ENTRY", "TOUCH", "CLOSE")):
        return "BUY"
    return "HOLD"


def _stringify_reason(trigger_event: dict[str, Any] | None) -> str:
    if not trigger_event:
        return "trigger_event"

    for candidate in (
        trigger_event.get("event_reason"),
        trigger_event.get("reason"),
        trigger_event.get("trigger_basis"),
        trigger_event.get("status"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return "trigger_event"


def _collect_symbols(
    trigger_symbol: str,
    active_strategy: dict[str, Any] | None,
    portfolio_snapshot: dict[str, Any],
) -> list[str]:
    ordered_symbols: list[str] = []

    def register(symbol: Any) -> None:
        normalized = _normalize_symbol(symbol)
        if normalized not in ordered_symbols:
            ordered_symbols.append(normalized)

    register(trigger_symbol)
    for symbol in (active_strategy or {}).get("target_coins") or []:
        register(symbol)
    for position in portfolio_snapshot.get("positions", []):
        register(position.get("symbol"))
    return ordered_symbols or [DEFAULT_SYMBOL]


def _base_target_ratio(strategy_target_count: int) -> float:
    return min(0.45, max(0.15, 0.75 / max(strategy_target_count, 1)))


def _build_action(
    *,
    symbol: str,
    action: str,
    order_amount_krw: float,
    sizing_mode: str,
    current_ratio: float,
    target_ratio: float | None,
    reasoning: list[str],
    checks: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": _normalize_symbol(symbol),
        "action": action,
        "order_amount_krw": round(max(order_amount_krw, 0.0), 2),
        "sizing_mode": sizing_mode,
        "current_allocation_ratio": round(max(current_ratio, 0.0), 4),
        "target_allocation_ratio": round(target_ratio, 4) if target_ratio is not None else None,
        "reasoning": reasoning,
        "checks": checks,
    }
    return payload


def _build_hold_action(
    symbol: str,
    current_ratio: float,
    reasoning: list[str],
    checks: dict[str, Any],
) -> dict[str, Any]:
    return _build_action(
        symbol=symbol,
        action="HOLD",
        order_amount_krw=0.0,
        sizing_mode="hold",
        current_ratio=current_ratio,
        target_ratio=current_ratio,
        reasoning=reasoning,
        checks=checks,
    )


def _summarize_actions(actions: list[dict[str, Any]]) -> str:
    active_actions = [action for action in actions if action.get("action") != "HOLD" and action.get("order_amount_krw", 0.0) > 0]
    if not active_actions:
        return "HOLD"
    if len(active_actions) > 1:
        return "REBALANCE"
    return active_actions[0].get("action", "HOLD")


def _build_fallback_plan(
    trigger_event: dict[str, Any] | None,
    active_strategy: dict[str, Any] | None,
    portfolio_snapshot: dict[str, Any],
) -> dict[str, Any]:
    trigger_symbol = _extract_trigger_symbol(trigger_event, active_strategy)
    trigger_action = _extract_trigger_action(trigger_event)
    trigger_reason = _stringify_reason(trigger_event)

    totals = portfolio_snapshot.get("totals", {})
    cash = portfolio_snapshot.get("cash", {})
    portfolio_value = max(_safe_float(totals.get("portfolio_value_krw"), 0.0), 0.0)
    cash_available = max(_safe_float(cash.get("available_krw"), 0.0), 0.0)
    cash_ratio = _safe_float(totals.get("cash_ratio"), 0.0)

    strategy_targets = [_normalize_symbol(symbol) for symbol in ((active_strategy or {}).get("target_coins") or [])]
    tracked_symbols = _collect_symbols(trigger_symbol, active_strategy, portfolio_snapshot)
    target_count = max(len(strategy_targets) or len(tracked_symbols), 1)
    base_target_ratio = _base_target_ratio(target_count)

    trigger_position = get_position_for_symbol(portfolio_snapshot, trigger_symbol)
    trigger_value = _safe_float((trigger_position or {}).get("market_value_krw"), 0.0)
    trigger_ratio = _safe_float((trigger_position or {}).get("allocation_ratio"), 0.0)

    top_reasoning = [
        f"Monitoring trigger '{trigger_reason}' was received for {trigger_symbol}.",
        f"Current available cash is {cash_available:,.0f} KRW and cash ratio is {cash_ratio:.2%}.",
    ]
    actions: list[dict[str, Any]] = []

    if trigger_action == "BUY":
        checks = {
            "has_cash": cash_available > 0,
            "has_position": trigger_value > 0,
            "position_conflict": bool(strategy_targets) and trigger_symbol not in strategy_targets,
            "portfolio_concentration_warning": trigger_ratio >= CONCENTRATION_WARNING_RATIO,
        }

        if cash_available <= 0:
            actions.append(
                _build_hold_action(
                    trigger_symbol,
                    trigger_ratio,
                    [
                        "현재 주문 가능한 예수금이 없어 BUY 제안을 보류합니다.",
                        f"트리거는 '{trigger_reason}' 이며 Owl이 재검토해야 합니다.",
                    ],
                    checks,
                )
            )
        else:
            desired_ratio = min(0.55, base_target_ratio + (0.10 if target_count == 1 else 0.05))
            amount_gap = max((desired_ratio - trigger_ratio) * portfolio_value, 0.0)
            primary_budget = min(
                cash_available * MAX_SINGLE_ACTION_CASH_SHARE,
                portfolio_value * 0.15 if portfolio_value else cash_available,
            )
            buy_amount = min(max(amount_gap, MIN_ACTION_AMOUNT_KRW), primary_budget, cash_available)

            if buy_amount >= MIN_ACTION_AMOUNT_KRW:
                actions.append(
                    _build_action(
                        symbol=trigger_symbol,
                        action="BUY",
                        order_amount_krw=buy_amount,
                        sizing_mode="fixed_amount",
                        current_ratio=trigger_ratio,
                        target_ratio=desired_ratio,
                        reasoning=[
                            f"{trigger_symbol} is the triggered market and remains aligned with the active strategy.",
                            f"Current allocation {trigger_ratio:.2%} is below the desired range near {desired_ratio:.2%}.",
                            f"Use approximately {buy_amount:,.0f} KRW for this entry and leave final approval to Owl.",
                        ],
                        checks=checks,
                    )
                )

            other_buy_budget = max(0.0, min(cash_available, cash_available * MAX_TOTAL_BUY_CASH_SHARE) - buy_amount)
            underweight_targets: list[tuple[str, float, float]] = []
            for symbol in strategy_targets:
                if symbol == trigger_symbol:
                    continue
                position = get_position_for_symbol(portfolio_snapshot, symbol)
                current_ratio = _safe_float((position or {}).get("allocation_ratio"), 0.0)
                target_ratio = base_target_ratio
                gap_amount = max((target_ratio - current_ratio) * portfolio_value, 0.0)
                if gap_amount >= MIN_ACTION_AMOUNT_KRW:
                    underweight_targets.append((symbol, current_ratio, gap_amount))

            remaining_targets = len(underweight_targets)
            for symbol, current_ratio, gap_amount in underweight_targets:
                if other_buy_budget < MIN_ACTION_AMOUNT_KRW or remaining_targets <= 0:
                    break
                amount = min(gap_amount, other_buy_budget / remaining_targets)
                if amount >= MIN_ACTION_AMOUNT_KRW:
                    actions.append(
                        _build_action(
                            symbol=symbol,
                            action="BUY",
                            order_amount_krw=amount,
                            sizing_mode="rebalance",
                            current_ratio=current_ratio,
                            target_ratio=base_target_ratio,
                            reasoning=[
                                f"{symbol} is also part of the active strategy target set.",
                                "Triggered entry on the lead market can be used to rebalance underweight companion assets.",
                            ],
                            checks={
                                "has_cash": cash_available > 0,
                                "has_position": _safe_float(
                                    (get_position_for_symbol(portfolio_snapshot, symbol) or {}).get("market_value_krw"),
                                    0.0,
                                )
                                > 0,
                                "position_conflict": False,
                                "portfolio_concentration_warning": current_ratio >= CONCENTRATION_WARNING_RATIO,
                            },
                        )
                    )
                    other_buy_budget -= amount
                remaining_targets -= 1

            for position in portfolio_snapshot.get("positions", []):
                symbol = _normalize_symbol(position.get("symbol"))
                if symbol == trigger_symbol:
                    continue
                current_ratio = _safe_float(position.get("allocation_ratio"), 0.0)
                current_value = _safe_float(position.get("market_value_krw"), 0.0)
                target_ratio = base_target_ratio if symbol in strategy_targets else 0.0
                if current_ratio <= target_ratio + OVERWEIGHT_REBALANCE_BUFFER:
                    continue
                trim_amount = min(current_value * 0.35, max((current_ratio - target_ratio) * portfolio_value, 0.0))
                if trim_amount < MIN_ACTION_AMOUNT_KRW:
                    continue
                actions.append(
                    _build_action(
                        symbol=symbol,
                        action="SELL",
                        order_amount_krw=trim_amount,
                        sizing_mode="rebalance",
                        current_ratio=current_ratio,
                        target_ratio=target_ratio,
                        reasoning=[
                            f"{symbol} currently looks overweight relative to the active strategy basket.",
                            "A partial trim can free budget and reduce concentration while the triggered asset is accumulated.",
                        ],
                        checks={
                            "has_cash": cash_available > 0,
                            "has_position": current_value > 0,
                            "position_conflict": False,
                            "portfolio_concentration_warning": current_ratio >= CONCENTRATION_WARNING_RATIO,
                        },
                    )
                )

    elif trigger_action == "SELL":
        checks = {
            "has_cash": cash_available > 0,
            "has_position": trigger_value > 0,
            "position_conflict": False,
            "portfolio_concentration_warning": trigger_ratio >= CONCENTRATION_WARNING_RATIO,
        }

        if trigger_value <= 0:
            actions.append(
                _build_hold_action(
                    trigger_symbol,
                    trigger_ratio,
                    [
                        f"{trigger_symbol} 보유 포지션이 없어 SELL 제안을 보류합니다.",
                        f"트리거는 '{trigger_reason}' 이며 Owl의 최종 검토가 필요합니다.",
                    ],
                    checks,
                )
            )
        else:
            is_hard_exit = any(keyword in trigger_reason.upper() for keyword in ("STOP", "LOSS", "LIQUIDATE"))
            target_ratio = 0.0 if is_hard_exit else min(base_target_ratio, trigger_ratio * 0.5)
            sell_amount = trigger_value if is_hard_exit else min(
                trigger_value,
                max(trigger_value * 0.5, max((trigger_ratio - target_ratio) * portfolio_value, 0.0)),
            )
            actions.append(
                _build_action(
                    symbol=trigger_symbol,
                    action="SELL",
                    order_amount_krw=sell_amount,
                    sizing_mode="liquidation" if is_hard_exit else "rebalance",
                    current_ratio=trigger_ratio,
                    target_ratio=target_ratio,
                    reasoning=[
                        f"{trigger_symbol} received a sell-side trigger '{trigger_reason}'.",
                        "The proposal reduces or exits the position first, then lets Owl confirm the final execution strength.",
                    ],
                    checks=checks,
                )
            )

    if not actions:
        checks = {
            "has_cash": cash_available > 0,
            "has_position": trigger_value > 0,
            "position_conflict": False,
            "portfolio_concentration_warning": trigger_ratio >= CONCENTRATION_WARNING_RATIO,
        }
        actions.append(
            _build_hold_action(
                trigger_symbol,
                trigger_ratio,
                [
                    "명확한 매수/매도 트리거 강도가 부족해 HOLD 제안서를 생성했습니다.",
                    "Owl이 전략 수정 필요 여부와 후속 타점 계산만 검토하면 됩니다.",
                ],
                checks,
            )
        )

    if len(actions) > 1:
        top_reasoning.append("이번 제안은 단일 주문보다 포트폴리오 재배치 성격이 강합니다.")
    if strategy_targets:
        top_reasoning.append(f"Active strategy target universe: {', '.join(strategy_targets)}.")

    return {
        "summary_action": _summarize_actions(actions),
        "actions": actions,
        "reasoning": top_reasoning,
        "next_step_for_owl": "final_decision",
    }


def _apply_soft_guardrails(
    plan: dict[str, Any],
    trigger_event: dict[str, Any] | None,
    active_strategy: dict[str, Any] | None,
    portfolio_snapshot: dict[str, Any],
) -> dict[str, Any]:
    normalized = BeaverPlanSchema(**plan).model_dump()
    strategy_targets = {_normalize_symbol(symbol) for symbol in ((active_strategy or {}).get("target_coins") or [])}
    cash_available = max(_safe_float(portfolio_snapshot.get("cash", {}).get("available_krw"), 0.0), 0.0)

    guarded_actions: list[dict[str, Any]] = []
    total_buy_amount = 0.0

    for raw_action in normalized.get("actions") or []:
        symbol = _normalize_symbol(raw_action.get("symbol"))
        action = str(raw_action.get("action") or "HOLD").upper()
        position = get_position_for_symbol(portfolio_snapshot, symbol)
        position_value = _safe_float((position or {}).get("market_value_krw"), 0.0)
        current_ratio = _safe_float((position or {}).get("allocation_ratio"), 0.0)
        availability = build_order_availability(portfolio_snapshot, symbol=symbol, side=action)

        reasoning = list(raw_action.get("reasoning") or [])
        checks = dict(raw_action.get("checks") or {})
        checks["has_cash"] = cash_available > 0
        checks["has_position"] = position_value > 0
        checks["portfolio_concentration_warning"] = current_ratio >= CONCENTRATION_WARNING_RATIO
        if action == "BUY":
            checks["position_conflict"] = bool(strategy_targets) and symbol not in strategy_targets
        else:
            checks["position_conflict"] = False

        amount = max(_safe_float(raw_action.get("order_amount_krw"), 0.0), 0.0)
        sizing_mode = raw_action.get("sizing_mode") or "hold"
        target_ratio = raw_action.get("target_allocation_ratio")

        if action == "BUY":
            if not availability.get("is_orderable"):
                guarded_actions.append(
                    _build_hold_action(
                        symbol,
                        current_ratio,
                        reasoning + ["예수금이 없어 BUY 제안을 HOLD로 완화했습니다."],
                        checks,
                    )
                )
                continue

            amount = min(amount, cash_available)
            if amount < MIN_ACTION_AMOUNT_KRW:
                guarded_actions.append(
                    _build_hold_action(
                        symbol,
                        current_ratio,
                        reasoning + ["제안 금액이 너무 작아 실질적 주문 대신 HOLD로 완화했습니다."],
                        checks,
                    )
                )
                continue

            guarded_actions.append(
                _build_action(
                    symbol=symbol,
                    action="BUY",
                    order_amount_krw=amount,
                    sizing_mode=sizing_mode,
                    current_ratio=current_ratio,
                    target_ratio=target_ratio,
                    reasoning=reasoning or ["Beaver가 매수 제안서를 생성했습니다."],
                    checks=checks,
                )
            )
            total_buy_amount += amount
            continue

        if action == "SELL":
            if not availability.get("is_orderable"):
                guarded_actions.append(
                    _build_hold_action(
                        symbol,
                        current_ratio,
                        reasoning + ["매도 가능한 포지션이 없어 SELL 제안을 HOLD로 완화했습니다."],
                        checks,
                    )
                )
                continue

            amount = min(amount, position_value)
            if amount < MIN_ACTION_AMOUNT_KRW:
                guarded_actions.append(
                    _build_hold_action(
                        symbol,
                        current_ratio,
                        reasoning + ["제안 금액이 너무 작아 SELL 대신 HOLD로 완화했습니다."],
                        checks,
                    )
                )
                continue

            guarded_actions.append(
                _build_action(
                    symbol=symbol,
                    action="SELL",
                    order_amount_krw=amount,
                    sizing_mode=sizing_mode,
                    current_ratio=current_ratio,
                    target_ratio=target_ratio,
                    reasoning=reasoning or ["Beaver가 매도 제안서를 생성했습니다."],
                    checks=checks,
                )
            )
            continue

        guarded_actions.append(
            _build_hold_action(
                symbol,
                current_ratio,
                reasoning or ["Beaver가 HOLD 제안서를 생성했습니다."],
                checks,
            )
        )

    if total_buy_amount > cash_available > 0:
        scale = cash_available / total_buy_amount
        rebalanced_actions: list[dict[str, Any]] = []
        for action in guarded_actions:
            if action.get("action") == "BUY":
                scaled_amount = round(_safe_float(action.get("order_amount_krw"), 0.0) * scale, 2)
                if scaled_amount < MIN_ACTION_AMOUNT_KRW:
                    rebalanced_actions.append(
                        _build_hold_action(
                            action.get("symbol", DEFAULT_SYMBOL),
                            _safe_float(action.get("current_allocation_ratio"), 0.0),
                            list(action.get("reasoning") or []) + ["총 매수 제안이 예수금을 초과해 HOLD로 완화했습니다."],
                            dict(action.get("checks") or {}),
                        )
                    )
                    continue
                action["order_amount_krw"] = scaled_amount
                action["reasoning"] = list(action.get("reasoning") or []) + ["총 매수 금액이 예수금을 넘지 않도록 자동 축소했습니다."]
            rebalanced_actions.append(action)
        guarded_actions = rebalanced_actions

    if not guarded_actions:
        guarded_actions = [
            _build_hold_action(
                _extract_trigger_symbol(trigger_event, active_strategy),
                0.0,
                ["Beaver가 기본 HOLD 제안서를 생성했습니다."],
                {
                    "has_cash": cash_available > 0,
                    "has_position": False,
                    "position_conflict": False,
                    "portfolio_concentration_warning": False,
                },
            )
        ]

    normalized["actions"] = guarded_actions
    normalized["summary_action"] = _summarize_actions(guarded_actions)
    normalized["reasoning"] = list(normalized.get("reasoning") or []) or [
        "Beaver가 Owl 검토용 분배 및 매매 제안서를 생성했습니다."
    ]
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
