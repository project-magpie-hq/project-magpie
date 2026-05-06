import datetime
import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from daemon.constant import SignalType
from db.entity import AssetEntity, WalletEntity
from db.mongo import wallets_collection
from tools.trade_history import register_trade_history

logger = logging.getLogger(__name__)


async def register_wallet(user_id: str, initial_balance: float = 100000000) -> WalletEntity:
    """사용자의 가상 지갑을 등록합니다. 만약, 이미 존재할 경우 초기화 합니다."""

    wallet_entity = WalletEntity.model_validate({"user_id": user_id, "balance": initial_balance})
    filter_query = {"user_id": user_id}

    print("\n" + "⚙️ " * 15)
    try:
        result = await wallets_collection.replace_one(filter_query, wallet_entity.model_dump(), upsert=True)
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
        wallet = await wallets_collection.find_one({"user_id": user_id})
    except Exception as e:
        logger.exception("가상 지갑 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 조회 중 DB 오류가 발생했습니다.") from e

    if wallet:
        wallet_entity = WalletEntity.model_validate(wallet)
        print(f"🪹 [The Nest]: 사용자({user_id})의 가상 지갑을 성공적으로 조회했습니다.")
        return wallet_entity

    print(f"🪹 [The Nest]: 사용자({user_id})의 가상 지갑을 찾을 수 없습니다.")
    return None


@tool
async def get_wallet(state: Annotated[dict, InjectedState]) -> WalletEntity | None:
    """사용자의 가상 지갑 현황을 확인합니다."""
    user_id: str = state["user_id"]

    return await fetch_wallet_by_user(user_id)


async def update_wallet(user_id: str, market: str, signal: SignalType, price: float, volume: float) -> WalletEntity:
    """체결 시 호출되어 지갑의 자산 상태를 수정합니다."""

    current_wallet = await wallets_collection.find_one({"user_id": user_id})
    if not current_wallet:
        raise ValueError(f"사용자({user_id})의 가상 지갑을 찾을 수 없습니다. 초기화를 먼저 진행하세요.")

    wallet = WalletEntity.model_validate(current_wallet)
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

    try:
        wallet.updated_at = datetime.datetime.now(datetime.UTC)
        await wallets_collection.replace_one({"user_id": user_id}, wallet.model_dump(by_alias=True))
    except Exception as e:
        logger.exception("가상 지갑 DB 수정 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 수정 중 DB 오류가 발생했습니다.") from e

    print(f"🪹 [The Nest]: [{signal.value.upper()}] 체결 완료: {market} | 가격: {price:,.0f} | 수량: {volume}")
    return wallet


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
    wallet = await update_wallet(user_id, market, signal, price, volume)
    await register_trade_history(user_id, market, signal, price, volume)

    return (
        f"✅ [체결 성공] {market} {signal.upper()} | "
        f"단가: {price:,.0f} | 수량: {volume} | "
        f"총액: {price * volume:,.0f} KRW\n"
        f"현재 원화 잔고: {wallet.balance:,.0f} KRW"
    )
