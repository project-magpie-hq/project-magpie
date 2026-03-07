"""
MongoDB 컬렉션 스키마 정의.

컬렉션:
  - strategies      : Meerkat이 생성한 전략 파라미터 및 성과 이력
  - trade_logs      : Owl이 실행한 매매 기록
  - asset_states    : 액션 이후 자산 스냅샷 (포트폴리오 상태)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def make_prompt_hash(prompt: str, symbol: str) -> str:
    """프롬프트 + 종목 조합의 SHA-256 해시를 반환한다."""
    raw = f"{prompt.strip().lower()}::{symbol.strip().upper()}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 공통 서브 도큐먼트
# ---------------------------------------------------------------------------

class IndicatorParam(BaseModel):
    """기술적 지표 파라미터 및 전략 내 가중치."""

    name: str
    """지표 이름. 예: 'RSI', 'MACD', 'EMA'"""

    params: dict[str, Any] = Field(default_factory=dict)
    """지표별 파라미터. 예: {'period': 14}"""

    weight: float = 1.0
    """전략 신호 산출 시 해당 지표의 가중치 (0.0 ~ 1.0)."""


class StrategyPerformance(BaseModel):
    """전략 성과 지표 (KPIs)."""

    profit_rate: float | None = None
    """수익률 (%)."""

    win_rate: float | None = None
    """승률 (%). 수익이 난 거래 수 / 전체 거래 수 * 100."""

    sharpe_ratio: float | None = None
    """샤프 지수. 초과 수익률 / 변동성."""

    max_drawdown: float | None = None
    """최대 낙폭, MDD (%). 고점 대비 최대 손실률."""

    total_trades: int = 0
    """평가 기간 내 총 거래 횟수."""

    evaluated_at: datetime | None = None
    """성과 산출 시각."""


class StrategyRevision(BaseModel):
    """전략 수정 이력 항목.

    Meerkat이 과거 성과를 분석하여 전략을 수정할 때마다 기록된다.
    """

    revised_at: datetime = Field(default_factory=_utcnow)

    reason: str
    """전략 수정 이유 — Meerkat의 Self-correction 분석 결과."""

    previous_indicators: list[IndicatorParam]
    """수정 전 지표 구성."""

    new_indicators: list[IndicatorParam]
    """수정 후 지표 구성."""

    previous_performance: StrategyPerformance | None = None
    """수정을 유발한 이전 전략의 성과 스냅샷."""


# ---------------------------------------------------------------------------
# strategies 컬렉션
# ---------------------------------------------------------------------------

class StrategyDocument(BaseModel):
    """strategies 컬렉션 도큐먼트.

    Meerkat Scanner가 생성하거나 수정한 투자 전략을 영속화한다.
    동일한 (prompt_hash, symbol) 조합에 대해 단 하나의 도큐먼트가 유지되며,
    전략이 수정될 때마다 revision_history에 이력이 누적된다.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=_new_id, alias="_id")

    prompt_hash: str
    """SHA-256(user_prompt + symbol). 동일 요청 재사용 여부 판단에 사용."""

    symbol: str
    """대상 종목. 예: 'BTC/USDT'"""

    style: str
    """매매 스타일. 예: 'aggressive', 'stable', 'balanced'"""

    indicators: list[IndicatorParam]
    """현재 활성 지표 구성."""

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    performance: StrategyPerformance | None = None
    """가장 최근 백테스트 성과."""

    revision_history: list[StrategyRevision] = Field(default_factory=list)
    """수정 이력 (오래된 순)."""


STRATEGY_INDEXES: list[IndexModel] = [
    IndexModel([("prompt_hash", ASCENDING), ("symbol", ASCENDING)], unique=True),
    IndexModel([("symbol", ASCENDING)]),
    IndexModel([("updated_at", DESCENDING)]),
]


# ---------------------------------------------------------------------------
# trade_logs 컬렉션
# ---------------------------------------------------------------------------

class TradeAction(str, Enum):
    """Owl Director가 선택 가능한 액션."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class TradeLogDocument(BaseModel):
    """trade_logs 컬렉션 도큐먼트.

    Owl Director가 매 시점마다 실행(또는 보류)한 액션을 기록한다.
    백테스팅 중에는 timestamp가 과거 시뮬레이션 시각을 가리킨다.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=_new_id, alias="_id")

    session_id: str
    """백테스트 세션 ID. 한 번의 시뮬레이션 실행 단위."""

    strategy_id: str
    """이 거래를 유발한 전략의 _id."""

    symbol: str
    """거래 종목. 예: 'BTC/USDT'"""

    action: TradeAction
    """실행된 액션."""

    price: float
    """체결 가격 (USDT 기준)."""

    quantity: float
    """거래 수량 (코인 단위). HOLD 시에는 0."""

    fee: float = 0.0
    """거래 수수료 (USDT 기준)."""

    timestamp: datetime
    """거래 시점 (백테스트: 시뮬레이션 기준 시각, 실거래: 실제 체결 시각)."""

    reasoning: str = ""
    """Owl이 해당 액션을 선택한 판단 근거 (LLM 출력 요약)."""


TRADE_LOG_INDEXES: list[IndexModel] = [
    IndexModel([("session_id", ASCENDING), ("timestamp", ASCENDING)]),
    IndexModel([("strategy_id", ASCENDING)]),
    IndexModel([("symbol", ASCENDING), ("timestamp", DESCENDING)]),
]


# ---------------------------------------------------------------------------
# asset_states 컬렉션
# ---------------------------------------------------------------------------

class Holding(BaseModel):
    """단일 종목 보유 정보."""

    symbol: str
    """보유 종목. 예: 'BTC/USDT'"""

    quantity: float
    """보유 수량 (코인 단위)."""

    avg_buy_price: float | None = None
    """평균 매수 단가 (USDT). 수익 계산에 사용."""


class AssetStateDocument(BaseModel):
    """asset_states 컬렉션 도큐먼트.

    매 액션 직후 자산 상태를 스냅샷으로 저장한다.
    MongoAssetProvider는 session_id 기준으로 가장 최신 도큐먼트를 조회하여
    가상 잔고와 포트폴리오 정보를 제공한다.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=_new_id, alias="_id")

    session_id: str
    """백테스트 세션 ID."""

    strategy_id: str | None = None
    """스냅샷을 유발한 전략 ID (선택)."""

    timestamp: datetime = Field(default_factory=_utcnow)
    """스냅샷 기록 시각."""

    cash_balance: float
    """현금 잔고 (USDT). 초기값: 시뮬레이션 초기 자본."""

    holdings: list[Holding] = Field(default_factory=list)
    """현재 보유 종목 목록."""

    total_value: float
    """현금 + 보유 종목 평가액의 합산."""


ASSET_STATE_INDEXES: list[IndexModel] = [
    IndexModel([("session_id", ASCENDING), ("timestamp", DESCENDING)]),
]


# ---------------------------------------------------------------------------
# 컬렉션 이름 상수
# ---------------------------------------------------------------------------

class CollectionName(StrEnum):
    """MongoDB 컬렉션 이름 열거형."""

    STRATEGIES = "strategies"
    TRADE_LOGS = "trade_logs"
    ASSET_STATES = "asset_states"


# ---------------------------------------------------------------------------
# 인덱스 초기화 유틸리티
# ---------------------------------------------------------------------------

async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """애플리케이션 시작 시 한 번 호출하여 모든 컬렉션 인덱스를 생성한다."""
    await db[CollectionName.STRATEGIES].create_indexes(STRATEGY_INDEXES)
    await db[CollectionName.TRADE_LOGS].create_indexes(TRADE_LOG_INDEXES)
    await db[CollectionName.ASSET_STATES].create_indexes(ASSET_STATE_INDEXES)
