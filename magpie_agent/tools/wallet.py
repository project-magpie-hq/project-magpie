import datetime
import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from bat_daemon.constant import SignalType
from db.entity import AssetEntity, WalletEntity, WalletTradeSnapshot
from db.mongo import get_wallets_collection
from magpie_agent.tools.telegram import send_telegram_message
from magpie_agent.tools.trade_history import register_trade_history

logger = logging.getLogger(__name__)


async def register_wallet(user_id: str, initial_balance: float = 100000000) -> WalletEntity:
    """사용자의 가상 지갑을 등록합니다. 만약, 이미 존재할 경우 초기화 합니다."""

    wallet_entity = WalletEntity.model_validate({"user_id": user_id, "balance": initial_balance})
    filter_query = {"user_id": user_id}

    print("\n" + "⚙️ " * 15)
    try:
        result = await get_wallets_collection().replace_one(filter_query, wallet_entity.model_dump(), upsert=True)
    except Exception as e:
        logger.exception("가상 지갑 DB 저장 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 저장 중 DB 오류가 발생했습니다.") from e

    if result.matched_count > 0:
        print(f"🪹 [The Nest]: 이미 지갑이 존재하여 초기 상태로 리셋되었습니다. user_id: {user_id})")
    else:
        print(f"🪹 [The Nest]: 새 가상 지갑이 성공적으로 등록되었습니다. user_id: {user_id})")

    print(f"🪹 [The Nest]: 초기 설정 자산: {initial_balance})")
    print("-" * 50)
    print("⚙️ " * 15 + "\n")

    return wallet_entity


async def fetch_wallet_by_user(user_id: str) -> WalletEntity | None:
    try:
        wallet = await get_wallets_collection().find_one({"user_id": user_id})
    except Exception as e:
        logger.exception("가상 지갑 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 조회 중 DB 오류가 발생했습니다.") from e

    if wallet:
        wallet_entity = WalletEntity.model_validate(wallet)
        print(f"🪹 [The Nest]: 사용자({user_id})의 가상 지갑을 성공적으로 조회했습니다.")
        return wallet_entity

    print(f"🪹 [The Nest]: 사용자({user_id})의 가상 지갑을 찾을 수 없습니다.")
    return None


def resolve_trade_volume_from_wallet(
    wallet: WalletEntity,
    market: str,
    signal: SignalType,
    price: float,
    *,
    buy_allocation_pct: float | None = None,
) -> float:
    """주어진 지갑 상태 기준으로 체결 가능한 수량을 계산합니다."""

    if signal == SignalType.BUY:
        if buy_allocation_pct is None:
            raise ValueError("BUY 체결에는 buy_allocation_pct가 필요합니다.")

        order_budget = wallet.balance * buy_allocation_pct
        if order_budget <= 0:
            raise ValueError("매수 예산이 0 이하입니다.")
        if wallet.balance < order_budget:
            raise ValueError(f"잔액 부족: 필요 {order_budget:,.0f} / 보유 {wallet.balance:,.0f}")
        return order_budget / price

    asset = wallet.assets.get(market)
    if asset is None or asset.volume <= 0:
        raise ValueError(f"매도 가능한 보유 수량이 없습니다: {market}")
    return asset.volume


def apply_trade_to_wallet_entity(
    wallet: WalletEntity,
    market: str,
    signal: SignalType,
    price: float,
    volume: float,
) -> WalletEntity:
    """DB 저장 없이 메모리 상의 WalletEntity에 체결 결과를 반영합니다."""

    total_price = price * volume

    if signal == SignalType.BUY:
        if wallet.balance < total_price:
            raise ValueError(f"잔액 부족: 필요 {total_price:,.0f} / 보유 {wallet.balance:,.0f}")

        wallet.balance -= total_price
        asset = wallet.assets.get(market, AssetEntity(volume=0.0, avg_buy_price=0.0))
        if asset is not None:
            new_volume = asset.volume + volume
            new_avg_price = ((asset.volume * asset.avg_buy_price) + total_price) / new_volume
            wallet.assets[market] = AssetEntity(volume=new_volume, avg_buy_price=new_avg_price)

    elif signal == SignalType.SELL:
        asset = wallet.assets.get(market)
        if asset is None or asset.volume < volume:
            raise ValueError(f"매도 수량 부족: 보유 {asset.volume if asset else 0} / 요청 {volume}")

        wallet.balance += total_price
        asset.volume -= volume
        if asset.volume == 0:
            wallet.assets.pop(market)
        else:
            wallet.assets[market] = asset

    wallet.updated_at = datetime.datetime.now(datetime.UTC)
    wallet.trade_stats.last_trade = WalletTradeSnapshot(
        market=market,
        signal=signal,
        price=price,
        volume=volume,
        total_price=total_price,
        executed_at=wallet.updated_at,
    )
    if signal == SignalType.BUY:
        wallet.trade_stats.total_buy_krw += total_price
        wallet.trade_stats.buy_count += 1
    else:
        wallet.trade_stats.total_sell_krw += total_price
        wallet.trade_stats.sell_count += 1

    return wallet


@tool
async def get_wallet(state: Annotated[dict, InjectedState]) -> WalletEntity | None:
    """사용자의 가상 지갑 현황을 확인합니다."""
    user_id: str = state["user_id"]

    return await fetch_wallet_by_user(user_id)


async def update_wallet(user_id: str, market: str, signal: SignalType, price: float, volume: float) -> WalletEntity:
    """체결 시 호출되어 지갑의 자산 상태를 수정합니다."""

    current_wallet = await get_wallets_collection().find_one({"user_id": user_id})
    if not current_wallet:
        raise ValueError(f"사용자({user_id})의 가상 지갑을 찾을 수 없습니다. 초기화를 먼저 진행하세요.")

    wallet = WalletEntity.model_validate(current_wallet)
    try:
        apply_trade_to_wallet_entity(wallet, market, signal, price, volume)
        await get_wallets_collection().replace_one({"user_id": user_id}, wallet.model_dump(by_alias=True))
    except Exception as e:
        logger.exception("가상 지갑 DB 수정 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 수정 중 DB 오류가 발생했습니다.") from e

    print(f"🪹 [The Nest]: [{signal.value.upper()}] 체결 완료: {market} | 가격: {price:,.0f} | 수량: {volume}")
    return wallet


async def notify_trade_execution(
    user_id: str,
    market: str,
    signal: SignalType,
    price: float,
    volume: float,
    wallet: WalletEntity,
) -> None:
    """체결 완료 후 텔레그램으로 지갑 현황을 알립니다."""

    total_price = price * volume

    assets_list = []
    for coin, asset in wallet.assets.items():
        if asset and asset.volume > 0:
            assets_list.append(f"• {coin}: {asset.volume:.4f} (평단: {asset.avg_buy_price:,.0f} 원)")

    holding_info = "\n".join(assets_list) if assets_list else "보유 코인 없음"

    notification_msg = (
        f"🚨 [매매 체결 알림]\n"
        f"코인: {market}\n"
        f"액션: {signal.value.upper()}\n"
        f"단가: {price:,.0f} 원\n"
        f"수량: {volume}\n"
        f"총액: {total_price:,.0f} 원\n\n"
        f"💰 전체 지갑 현황\n"
        f"보유 잔고: {wallet.balance:,.0f} 원\n"
        f"{holding_info}"
    )

    await send_telegram_message(chat_id=user_id, text=notification_msg)


async def finalize_trade_execution(
    user_id: str,
    market: str,
    signal: SignalType,
    price: float,
    volume: float,
) -> WalletEntity:
    """지갑 반영, 체결 이력 저장, 알림 전송까지 체결 마무리를 공통 처리합니다."""

    wallet = await update_wallet(user_id, market, signal, price, volume)
    await register_trade_history(user_id, market, signal, price, volume)
    await notify_trade_execution(user_id, market, signal, price, volume, wallet)
    return wallet


async def resolve_daemon_trade_volume(
    user_id: str,
    market: str,
    signal: SignalType,
    price: float,
    *,
    buy_allocation_pct: float | None = None,
) -> float:
    """Bat Daemon의 monitoring target 비율/전량 매도 규칙에 맞춰 체결 수량을 계산합니다."""

    wallet = await fetch_wallet_by_user(user_id)
    if wallet is None:
        raise ValueError(f"사용자({user_id})의 가상 지갑을 찾을 수 없습니다. 초기화를 먼저 진행하세요.")

    return resolve_trade_volume_from_wallet(
        wallet,
        market,
        signal,
        price,
        buy_allocation_pct=buy_allocation_pct,
    )


async def execute_trade_for_daemon(
    user_id: str,
    market: str,
    signal: SignalType,
    price: float,
    *,
    buy_allocation_pct: float | None = None,
) -> tuple[WalletEntity, float]:
    """Bat Daemon이 시그널 포착 직후 직접 체결할 때 사용하는 helper."""

    volume = await resolve_daemon_trade_volume(
        user_id,
        market,
        signal,
        price,
        buy_allocation_pct=buy_allocation_pct,
    )
    wallet = await finalize_trade_execution(user_id, market, signal, price, volume)
    return wallet, volume


@tool
async def process_trade_execution(
    market: str, signal: SignalType, price: float, volume: float, state: Annotated[dict, InjectedState]
) -> str:
    """
    매매 체결 시 호출되어 지갑의 자산 상태를 수정하고, 체결 이력을 DB에 등록합니다.
    잔고가 부족하거나 조건이 맞지 않으면 에러 메시지를 반환합니다.

    Args:
        market: 거래할 타겟 코인 (예: 'KRW-BTC')
        signal: 'BUY' (매수) 또는 'SELL' (매도)
        price: 체결 단가
        volume: 체결 수량
    """

    user_id: str = state["user_id"]
    wallet = await finalize_trade_execution(user_id, market, signal, price, volume)
    total_price = price * volume

    return (
        f"✅ [체결 성공] {market} {signal.value.upper()} | "
        f"단가: {price:,.0f} | 수량: {volume} | "
        f"총액: {total_price:,.0f} KRW\n"
        f"현재 원화 잔고: {wallet.balance:,.0f} KRW"
    )
