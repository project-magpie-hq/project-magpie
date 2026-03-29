from datetime import UTC, datetime
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from db.mongo import portfolio_snapshot_collection

DEFAULT_CURRENCY = "KRW"
DEFAULT_STARTING_CASH_KRW = 1_000_000.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(symbol: Any) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    if "-" in raw:
        return raw
    return f"{DEFAULT_CURRENCY}-{raw}"


def _build_default_snapshot(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "source": "default_stub",
        "as_of": datetime.now(UTC).isoformat(),
        "currency": DEFAULT_CURRENCY,
        "cash": {
            "available_krw": DEFAULT_STARTING_CASH_KRW,
            "locked_krw": 0.0,
            "total_krw": DEFAULT_STARTING_CASH_KRW,
        },
        "positions": [],
        "totals": {
            "portfolio_value_krw": DEFAULT_STARTING_CASH_KRW,
            "invested_value_krw": 0.0,
            "cash_ratio": 1.0,
        },
        "order_constraints": {
            "buy_available_krw": DEFAULT_STARTING_CASH_KRW,
            "sellable_symbols": [],
        },
    }


def _normalize_portfolio_snapshot(raw: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    if not raw:
        return _build_default_snapshot(user_id)

    cash_raw = raw.get("cash") if isinstance(raw.get("cash"), dict) else {}
    available_cash = _safe_float(
        cash_raw.get("available_krw", raw.get("available_cash_krw", raw.get("cash_balance_krw"))),
        DEFAULT_STARTING_CASH_KRW,
    )
    locked_cash = _safe_float(cash_raw.get("locked_krw", raw.get("locked_cash_krw")), 0.0)

    positions_input = raw.get("positions") if isinstance(raw.get("positions"), list) else []
    positions: list[dict[str, Any]] = []
    invested_value = 0.0
    sellable_symbols: list[str] = []

    for item in positions_input:
        symbol = _normalize_symbol(item.get("symbol") or item.get("market") or item.get("target_coin"))
        quantity = _safe_float(item.get("quantity", item.get("qty")), 0.0)
        avg_entry_price = _safe_float(item.get("avg_entry_price"), 0.0)
        current_price = _safe_float(item.get("current_price"), avg_entry_price)
        market_value = _safe_float(item.get("market_value_krw"), quantity * current_price)

        if not symbol:
            continue

        invested_value += market_value
        if quantity > 0:
            sellable_symbols.append(symbol)

        positions.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "avg_entry_price": avg_entry_price,
                "current_price": current_price,
                "market_value_krw": market_value,
                "allocation_ratio": 0.0,
            }
        )

    cash_total = available_cash + locked_cash
    portfolio_value = max(_safe_float(raw.get("portfolio_value_krw"), cash_total + invested_value), 0.0)

    if portfolio_value <= 0:
        portfolio_value = cash_total + invested_value
    if portfolio_value <= 0:
        return _build_default_snapshot(user_id)

    for position in positions:
        position["allocation_ratio"] = round(position["market_value_krw"] / portfolio_value, 4)

    return {
        "user_id": user_id,
        "source": raw.get("source", "state_or_db"),
        "as_of": raw.get("as_of") or datetime.now(UTC).isoformat(),
        "currency": raw.get("currency", DEFAULT_CURRENCY),
        "cash": {
            "available_krw": available_cash,
            "locked_krw": locked_cash,
            "total_krw": cash_total,
        },
        "positions": positions,
        "totals": {
            "portfolio_value_krw": portfolio_value,
            "invested_value_krw": invested_value,
            "cash_ratio": round(cash_total / portfolio_value, 4) if portfolio_value else 0.0,
        },
        "order_constraints": {
            "buy_available_krw": _safe_float(raw.get("buy_available_krw"), available_cash),
            "sellable_symbols": sellable_symbols,
        },
    }


async def load_portfolio_snapshot_for_user(state: dict[str, Any]) -> dict[str, Any]:
    user_id = state.get("user_id", "default_user")

    if isinstance(state.get("portfolio_snapshot"), dict):
        return _normalize_portfolio_snapshot(state.get("portfolio_snapshot"), user_id)

    # TODO: 실제 거래소/브로커 계좌 API 연동 시 이 지점을 교체한다.
    snapshot_doc = await portfolio_snapshot_collection.find_one({"user_id": user_id}, sort=[("updated_at", -1)])
    return _normalize_portfolio_snapshot(snapshot_doc, user_id)


def get_position_for_symbol(snapshot: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    normalized_symbol = _normalize_symbol(symbol)
    for position in snapshot.get("positions", []):
        if position.get("symbol") == normalized_symbol:
            return position
    return None


def build_order_availability(snapshot: dict[str, Any], symbol: str | None = None, side: str | None = None) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_side = str(side or "").upper()
    cash_available = _safe_float(snapshot.get("cash", {}).get("available_krw"), 0.0)
    position = get_position_for_symbol(snapshot, normalized_symbol) if normalized_symbol else None
    market_value = _safe_float(position.get("market_value_krw") if position else 0.0, 0.0)

    can_buy = cash_available > 0
    can_sell = market_value > 0

    if normalized_side == "BUY":
        return {
            "side": "BUY",
            "symbol": normalized_symbol,
            "is_orderable": can_buy,
            "available_amount_krw": cash_available,
        }

    if normalized_side == "SELL":
        return {
            "side": "SELL",
            "symbol": normalized_symbol,
            "is_orderable": can_sell,
            "available_amount_krw": market_value,
        }

    return {
        "symbol": normalized_symbol,
        "buy_available_krw": cash_available,
        "sell_available_krw": market_value,
        "can_buy": can_buy,
        "can_sell": can_sell,
    }


@tool
async def get_portfolio_snapshot(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """사용자의 현재 예수금/보유자산/비중을 한 번에 조회합니다."""
    return await load_portfolio_snapshot_for_user(state)


@tool
async def get_available_cash(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """현재 주문 가능한 예수금 정보를 조회합니다."""
    snapshot = await load_portfolio_snapshot_for_user(state)
    return {
        "currency": snapshot.get("currency", DEFAULT_CURRENCY),
        "available_cash_krw": snapshot.get("cash", {}).get("available_krw", 0.0),
        "locked_cash_krw": snapshot.get("cash", {}).get("locked_krw", 0.0),
        "total_cash_krw": snapshot.get("cash", {}).get("total_krw", 0.0),
    }


@tool
async def get_current_positions(state: Annotated[dict, InjectedState]) -> list[dict[str, Any]]:
    """현재 보유 자산/포지션 목록을 조회합니다."""
    snapshot = await load_portfolio_snapshot_for_user(state)
    return snapshot.get("positions", [])


@tool
async def get_portfolio_allocations(state: Annotated[dict, InjectedState]) -> dict[str, Any]:
    """자산별 현재 비중과 평가금액을 조회합니다."""
    snapshot = await load_portfolio_snapshot_for_user(state)
    allocations = [
        {
            "symbol": position.get("symbol"),
            "allocation_ratio": position.get("allocation_ratio", 0.0),
            "market_value_krw": position.get("market_value_krw", 0.0),
        }
        for position in snapshot.get("positions", [])
    ]
    return {
        "portfolio_value_krw": snapshot.get("totals", {}).get("portfolio_value_krw", 0.0),
        "allocations": allocations,
    }


@tool
async def get_order_availability(
    symbol: str | None = None,
    side: str | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> dict[str, Any]:
    """심볼 기준 단순 주문 가능 여부와 주문 가능 금액을 조회합니다."""
    snapshot = await load_portfolio_snapshot_for_user(state or {})
    return build_order_availability(snapshot, symbol=symbol, side=side)
