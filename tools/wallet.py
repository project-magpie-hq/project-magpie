import datetime
import logging
from typing import Literal

from langchain_core.tools import tool

from db.entity import WalletEntity, AssetEntity
from db.mongo import wallets_collection

logger = logging.getLogger(__name__)


@tool
async def register_wallet(user_id: str, initial_balance: float = 100000000) -> WalletEntity:
    """사용자의 가상 지갑을 등록합니다. 만약, 이미 존재할 경우 초기화 합니다."""

    wallet_entity = WalletEntity.model_validate(
        {"user_id": user_id, "balance": initial_balance}
    )
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


@tool
async def get_wallet(user_id: str) -> WalletEntity | None:
    """사용자의 가상 지갑 현황을 확인합니다."""
    user_id: str = user_id

    try:
        wallet = await wallets_collection.find_one({"user_id": user_id})
    except Exception as e:
        logger.exception("가상 지갑 DB 조회 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 조회 중 DB 오류가 발생했습니다.") from e

    if wallet:
        wallet_entity = WalletEntity.model_validate(wallet)
        print(f"🪹 [The Nest]: 사용자({user_id})의 가상 지갑을 성공적으로 조회했습니다.")
        return wallet_entity
    else:
        print(f"🪹 [The Nest]: 사용자({user_id})의 가상 지갑을 찾을 수 없습니다.")
        return None


@tool
def update_wallet(user_id: str, market: str, type: Literal["buy", "sell"], price: float, volume: float) -> WalletEntity:
    """체결 시 호출되어 지갑의 자산 상태를 수정합니다."""

    current_wallet = wallets_collection.find_one({"user_id": user_id})
    if not current_wallet:
        raise ValueError(f"사용자({user_id})의 가상 지갑을 찾을 수 없습니다. 초기화를 먼저 진행하세요.")

    wallet = WalletEntity.model_validate(**current_wallet)
    total_krw = price * volume

    if type == 'buy':
        if wallet.balance < total_krw:
            raise ValueError(f"잔액 부족: 필요 {total_krw:,.0f} / 보유 {wallet.balance:,.0f}")

        wallet.balance -= total_krw

        asset = wallet.assets.get(market, AssetEntity(volume=0.0, avg_buy_price=0.0))
        new_volume = asset.volume + volume
        new_avg_price = ((asset.volume * asset.avg_buy_price) + total_krw) / new_volume

        wallet.assets[market] = AssetEntity(volume=new_volume, avg_buy_price=new_avg_price)

    elif type == 'sell':
        asset = wallet.assets.get(market)
        if not asset or asset.volume < volume:
            raise ValueError(f"매도 수량 부족: 보유 {asset.volume if asset else 0} / 요청 {volume}")

        wallet.balance += total_krw

        asset.volume -= volume
        if asset.volume == 0:
            wallet.assets.pop(market)
        else:
            wallet.assets[market] = asset

    try:
        wallet.updated_at = datetime.datetime.now(datetime.UTC)
        wallets_collection.replace_one({"user_id": user_id}, wallet.model_dump(by_alias=True))
    except Exception as e:
        logger.exception("가상 지갑 DB 수정 실패 (user_id: %s)", user_id)
        raise RuntimeError("가상 지갑 수정 중 DB 오류가 발생했습니다.") from e

    print(f"🪹 [The Nest]: [{type.upper()}] 체결 완료: {market} | 가격: {price:,.0f} | 수량: {volume}")
    return wallet
