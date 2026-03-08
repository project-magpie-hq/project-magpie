"""
UpbitAssetProvider — 실거래 모드 AssetProvider 구현체.

pyupbit API를 통해 실제 업비트 계정의 잔고와 포트폴리오를 조회한다.
pyupbit의 함수는 동기이므로 asyncio.to_thread로 래핑한다.

환경변수:
    UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY (.env)
"""

from __future__ import annotations

import asyncio
import logging
import os

import pyupbit
from dotenv import load_dotenv

from providers.base import (AssetProvider, BalanceInfo, HoldingInfo,
                            PortfolioInfo, ProviderMode)

load_dotenv()
logger = logging.getLogger(__name__)


class UpbitAssetProvider(AssetProvider):
    """실거래 모드 AssetProvider.

    업비트 계정의 실제 KRW 잔고와 보유 코인을 반환한다.

    Args:
        access_key: 업비트 Open API Access Key.
                    미전달 시 환경변수 UPBIT_ACCESS_KEY 사용.
        secret_key: 업비트 Open API Secret Key.
                    미전달 시 환경변수 UPBIT_SECRET_KEY 사용.
    """

    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        ak = access_key or os.getenv("UPBIT_ACCESS_KEY", "")
        sk = secret_key or os.getenv("UPBIT_SECRET_KEY", "")
        if not ak or not sk:
            raise ValueError(
                "업비트 API 키가 설정되지 않았습니다. "
                ".env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 를 입력하세요."
            )
        self._upbit = pyupbit.Upbit(ak, sk)

    # ------------------------------------------------------------------
    # AssetProvider 인터페이스 구현
    # ------------------------------------------------------------------

    @property
    def mode(self) -> ProviderMode:
        return ProviderMode.REAL

    async def get_balance(self) -> BalanceInfo:
        """업비트 계정의 KRW 잔고를 반환한다."""
        krw = await asyncio.to_thread(self._upbit.get_balance, "KRW")
        if krw is None:
            logger.warning("[UpbitAssetProvider] KRW 잔고 조회 실패, 0 반환")
            krw = 0.0
        logger.debug("[UpbitAssetProvider] KRW 잔고: %.2f", krw)
        return BalanceInfo(cash=float(krw), currency="KRW")

    async def get_portfolio(self) -> PortfolioInfo:
        """업비트 계정의 전체 포트폴리오(KRW + 보유 코인)를 반환한다."""
        balances: list[dict] = await asyncio.to_thread(self._upbit.get_balances)
        if balances is None:
            balances = []

        krw_cash = 0.0
        holdings: list[HoldingInfo] = []

        for b in balances:
            currency = b.get("currency", "")
            qty = float(b.get("balance", 0.0)) + float(b.get("locked", 0.0))
            avg_price = float(b.get("avg_buy_price", 0.0))

            if currency == "KRW":
                krw_cash = qty
            elif qty > 0:
                holdings.append(
                    HoldingInfo(
                        symbol=f"KRW-{currency}",
                        quantity=qty,
                        avg_buy_price=avg_price if avg_price > 0 else None,
                    )
                )

        # 보유 코인 현재가 조회로 총 평가액 계산
        total_value = krw_cash
        for h in holdings:
            price = await asyncio.to_thread(pyupbit.get_current_price, h.symbol)
            if price:
                total_value += h.quantity * float(price)

        logger.debug(
            "[UpbitAssetProvider] 포트폴리오 조회 완료 — KRW=%.0f, 종목=%d개, 총평가=%.0f",
            krw_cash, len(holdings), total_value,
        )
        return PortfolioInfo(
            cash=krw_cash,
            currency="KRW",
            holdings=holdings,
            total_value=total_value,
        )

    # ------------------------------------------------------------------
    # 실주문 메서드
    # ------------------------------------------------------------------

    async def buy_market_order(self, symbol: str, krw_amount: float) -> dict | None:
        """시장가 매수 (KRW 금액 기준).

        Args:
            symbol:     업비트 마켓 코드. 예: 'KRW-BTC'.
            krw_amount: 매수에 사용할 KRW 금액.

        Returns:
            업비트 주문 응답 dict, 실패 시 None.
        """
        logger.info("[UpbitAssetProvider] 시장가 매수 — %s %.0f KRW", symbol, krw_amount)
        result = await asyncio.to_thread(self._upbit.buy_market_order, symbol, krw_amount)
        if result is None or "error" in (result or {}):
            logger.error("[UpbitAssetProvider] 매수 실패: %s", result)
        return result

    async def sell_market_order(self, symbol: str, volume: float) -> dict | None:
        """시장가 매도 (코인 수량 기준).

        Args:
            symbol: 업비트 마켓 코드. 예: 'KRW-BTC'.
            volume: 매도할 코인 수량.

        Returns:
            업비트 주문 응답 dict, 실패 시 None.
        """
        logger.info("[UpbitAssetProvider] 시장가 매도 — %s %.8f", symbol, volume)
        result = await asyncio.to_thread(self._upbit.sell_market_order, symbol, volume)
        if result is None or "error" in (result or {}):
            logger.error("[UpbitAssetProvider] 매도 실패: %s", result)
        return result
