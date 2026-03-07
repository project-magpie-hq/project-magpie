"""
MongoAssetProvider — 백테스트 모드 AssetProvider 구현체.

MongoDB의 asset_states 컬렉션에서 session_id 기준으로
가장 최신 자산 스냅샷을 조회하여 가상 잔고와 포트폴리오 정보를 제공한다.

초기 자본 세팅:
    백테스트 시작 시 아래와 같이 초기 스냅샷을 삽입한다.

    .. code-block:: python

        await MongoAssetProvider.initialize_session(
            db=db,
            session_id="sess-001",
            initial_cash=10_000.0,
        )

사용 예시:
    .. code-block:: python

        provider = MongoAssetProvider(db=db, session_id="sess-001")

        balance   = await provider.get_balance()
        portfolio = await provider.get_portfolio()
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from db.schemas import AssetStateDocument, CollectionName, Holding
from providers.base import (AssetProvider, BalanceInfo, HoldingInfo,
                            PortfolioInfo, ProviderMode)

logger = logging.getLogger(__name__)


class MongoAssetProvider(AssetProvider):
    """백테스트 모드 AssetProvider.

    매 액션 후 asset_states 컬렉션에 스냅샷이 기록된다는 가정 하에,
    session_id로 필터링한 도큐먼트 중 timestamp가 가장 최근인 것을 읽는다.

    Args:
        db:         motor AsyncIOMotorDatabase 인스턴스.
        session_id: 조회 대상 백테스트 세션 ID.
    """

    def __init__(self, db: AsyncIOMotorDatabase, session_id: str) -> None:
        self._db = db
        self._session_id = session_id

    # ------------------------------------------------------------------
    # AssetProvider 인터페이스 구현
    # ------------------------------------------------------------------

    @property
    def mode(self) -> ProviderMode:
        return ProviderMode.BACKTEST

    async def get_balance(self) -> BalanceInfo:
        """MongoDB에서 최신 자산 스냅샷을 조회하여 현금 잔고를 반환한다.

        스냅샷이 존재하지 않으면 cash=0.0 을 반환하고 경고 로그를 남긴다.
        """
        doc = await self._latest_snapshot()
        if doc is None:
            logger.warning(
                "[MongoAssetProvider] session_id=%s 에 해당하는 자산 스냅샷이 없습니다.",
                self._session_id,
            )
            return BalanceInfo(cash=0.0)

        return BalanceInfo(cash=doc["cash_balance"])

    async def get_portfolio(self) -> PortfolioInfo:
        """MongoDB에서 최신 자산 스냅샷을 조회하여 전체 포트폴리오를 반환한다.

        스냅샷이 존재하지 않으면 빈 포트폴리오를 반환하고 경고 로그를 남긴다.
        """
        doc = await self._latest_snapshot()
        if doc is None:
            logger.warning(
                "[MongoAssetProvider] session_id=%s 에 해당하는 자산 스냅샷이 없습니다.",
                self._session_id,
            )
            return PortfolioInfo(cash=0.0)

        holdings = [
            HoldingInfo(
                symbol=h["symbol"],
                quantity=h["quantity"],
                avg_buy_price=h.get("avg_buy_price"),
            )
            for h in doc.get("holdings", [])
        ]

        return PortfolioInfo(
            cash=doc["cash_balance"],
            holdings=holdings,
            total_value=doc["total_value"],
        )

    # ------------------------------------------------------------------
    # 상태 변경 메서드
    # ------------------------------------------------------------------

    async def save_snapshot(
        self,
        cash_balance: float,
        holdings: list[Holding],
        total_value: float,
        strategy_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> str:
        """현재 자산 상태를 asset_states 컬렉션에 스냅샷으로 저장한다.

        Backtest Engine이 매 액션 후 호출하여 포트폴리오 이력을 쌓는다.

        Args:
            cash_balance:  현금 잔고.
            holdings:      보유 종목 목록.
            total_value:   현금 + 보유 종목 평가액 합산.
            strategy_id:   관련 전략 ID (선택).
            timestamp:     스냅샷 시각. None이면 현재 UTC 시각 사용.

        Returns:
            저장된 도큐먼트의 _id.
        """
        doc = AssetStateDocument(
            session_id=self._session_id,
            strategy_id=strategy_id,
            timestamp=timestamp or datetime.now(UTC),
            cash_balance=cash_balance,
            holdings=holdings,
            total_value=total_value,
        )
        payload = doc.model_dump(by_alias=True)
        await self._db[CollectionName.ASSET_STATES].insert_one(payload)
        logger.debug(
            "[MongoAssetProvider] 스냅샷 저장 완료 — session=%s, cash=%.2f, total=%.2f",
            self._session_id,
            cash_balance,
            total_value,
        )
        return doc.id

    # ------------------------------------------------------------------
    # 클래스 메서드 유틸리티
    # ------------------------------------------------------------------

    @classmethod
    async def initialize_session(
        cls,
        db: AsyncIOMotorDatabase,
        session_id: str,
        initial_cash: float = 10_000.0,
        currency: str = "USDT",
        timestamp: datetime | None = None,
    ) -> "MongoAssetProvider":
        """백테스트 세션의 초기 자산 스냅샷을 삽입하고 Provider를 반환한다.

        백테스트 엔진의 시작 지점에서 한 번 호출한다.

        Args:
            db:           motor AsyncIOMotorDatabase 인스턴스.
            session_id:   신규 백테스트 세션 ID.
            initial_cash: 시뮬레이션 초기 자본. 기본값 10,000 USDT.
            currency:     현금 화폐 단위 (현재는 표기용).
            timestamp:    초기 스냅샷 시각. None이면 현재 UTC 시각 사용.

        Returns:
            초기화된 MongoAssetProvider 인스턴스.
        """
        doc = AssetStateDocument(
            session_id=session_id,
            timestamp=timestamp or datetime.now(UTC),
            cash_balance=initial_cash,
            holdings=[],
            total_value=initial_cash,
        )
        await db[CollectionName.ASSET_STATES].insert_one(doc.model_dump(by_alias=True))
        logger.info(
            "[MongoAssetProvider] 세션 초기화 완료 — session=%s, initial_cash=%.2f %s",
            session_id,
            initial_cash,
            currency,
        )
        return cls(db=db, session_id=session_id)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _latest_snapshot(self) -> dict | None:
        """session_id 기준으로 가장 최신 asset_states 도큐먼트를 반환한다."""
        return await self._db[CollectionName.ASSET_STATES].find_one(
            {"session_id": self._session_id},
            sort=[("timestamp", -1)],
        )
