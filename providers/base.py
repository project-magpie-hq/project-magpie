"""
AssetProvider 추상 인터페이스.

실제 환경 전환(백테스트 ↔ 실거래)을 고려하여
자산 정보를 가져오는 인터페이스를 추상화한다.

구현체:
  - MongoAssetProvider  : 백테스트 모드 — MongoDB 가상 잔고 조회
  - UpbitAssetProvider  : 실거래 모드 — 업비트 API 실자산 조회
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 모드 열거형
# ---------------------------------------------------------------------------

class ProviderMode(str, Enum):
    """AssetProvider 동작 모드."""

    BACKTEST = "backtest"
    """백테스트: MongoDB 가상 자산 조회."""

    REAL = "real"
    """실거래: 거래소 API 실자산 조회."""


# ---------------------------------------------------------------------------
# 반환 데이터 모델
# ---------------------------------------------------------------------------

class BalanceInfo(BaseModel):
    """현금 잔고 정보."""

    cash: float
    """사용 가능한 현금 잔액."""

    currency: str = "KRW"
    """잔고 화폐 단위."""

    @property
    def is_empty(self) -> bool:
        return self.cash <= 0.0


class HoldingInfo(BaseModel):
    """단일 종목 보유 정보."""

    symbol: str
    """종목 심볼. 예: 'KRW-BTC'"""

    quantity: float
    """보유 수량 (코인 단위)."""

    avg_buy_price: float | None = None
    """평균 매수 단가. 평가 손익 계산에 사용."""


class PortfolioInfo(BaseModel):
    """전체 포트폴리오 정보 (현금 + 보유 종목)."""

    cash: float
    """현금 잔액."""

    currency: str = "KRW"
    """현금 화폐 단위."""

    holdings: list[HoldingInfo] = Field(default_factory=list)
    """보유 중인 종목 목록."""

    total_value: float = 0.0
    """현금 + 보유 종목 평가액 합산."""

    @property
    def symbols(self) -> list[str]:
        """현재 보유 중인 종목 심볼 목록을 반환한다."""
        return [h.symbol for h in self.holdings]

    @property
    def is_all_cash(self) -> bool:
        """보유 종목 없이 전량 현금 상태인지 여부."""
        return len(self.holdings) == 0


# ---------------------------------------------------------------------------
# 추상 인터페이스
# ---------------------------------------------------------------------------

class AssetProvider(ABC):
    """자산 정보 추상 인터페이스.

    백테스트 모드에서는 MongoDB 가상 잔고를,
    실거래 모드에서는 업비트 API 실잔고를 반환한다.

    모든 메서드는 async로 구현되어야 하며,
    구현체는 이 클래스를 상속하여 두 추상 메서드를 반드시 오버라이드해야 한다.

    Example::

        provider: AssetProvider = MongoAssetProvider(db, session_id="sess-001")

        balance = await provider.get_balance()
        print(f"잔고: {balance.cash} {balance.currency}")

        portfolio = await provider.get_portfolio()
        for h in portfolio.holdings:
            print(f"{h.symbol}: {h.quantity} @ {h.avg_buy_price}")
    """

    @property
    @abstractmethod
    def mode(self) -> ProviderMode:
        """이 Provider의 동작 모드를 반환한다."""
        ...

    @abstractmethod
    async def get_balance(self) -> BalanceInfo:
        """현재 현금 잔고를 조회한다.

        Returns:
            BalanceInfo: 현금 잔액 및 화폐 단위.
        """
        ...

    @abstractmethod
    async def get_portfolio(self) -> PortfolioInfo:
        """전체 포트폴리오(현금 + 보유 종목)를 조회한다.

        Returns:
            PortfolioInfo: 현금, 보유 종목 목록, 평가 총액.
        """
        ...
