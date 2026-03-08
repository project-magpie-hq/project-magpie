"""
백테스트 엔진 — 시뮬레이터 루프 핵심 모듈.

흐름:
  1. Meerkat LangGraph 실행 → 전략 설계 및 MongoDB 저장
  2. 업비트 OpenAPI로 전체 OHLCV 로드
  3. MongoAssetProvider로 가상 자산 초기화 (초기 자본 세팅)
  4. 봉 단위 루프:
       - 현재 윈도우 → Owl Director 판단 (BUY / SELL / HOLD)
       - 가상 포트폴리오 업데이트 (수수료 포함)
       - MongoDB에 TradeLog + AssetState 저장
  5. BacktestResult 반환 → Reporter가 KPI 산출

수수료 정책:
  - 업비트 현물 매매 기본 수수료 0.05 % 적용
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from agents.owl_director.decision import OwlAction, OwlDecision, owl_decide
from core.constants import FEE_RATE
from core.graph import fetch_ohlcv, run_meerkat
from db.connection import get_db
from db.schemas import CollectionName, Holding, TradeAction, TradeLogDocument
from providers.base import ProviderMode
from providers.mongo import MongoAssetProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 설정 / 결과 데이터 모델
# ---------------------------------------------------------------------------

class EngineConfig(BaseModel):
    """백테스트 / 실거래 공용 엔진 설정."""

    symbol: str
    """업비트 마켓 코드. 예: 'KRW-BTC'"""

    style: str
    """매매 스타일. 'aggressive' | 'stable' | 'balanced'"""

    user_prompt: str
    """사용자 원본 요청 (Meerkat 전략 해시 생성에 사용)."""

    mode: ProviderMode = ProviderMode.BACKTEST
    """실행 모드.

    - ``ProviderMode.BACKTEST`` : MongoDB 가상 잔고 + 과거 데이터 시뮬레이션
    - ``ProviderMode.REAL``      : 업비트 실계좌 + 실시간 매매 (LiveEngine 사용)
    """

    initial_cash: float = Field(default=10_000.0, gt=0)
    """시뮬레이션 초기 자본 (KRW 단위). BACKTEST 모드에서만 사용."""

    interval: str = "day"
    """OHLCV 캔들 단위. 'day' | 'minute60' 등."""

    candle_count: int = Field(default=200, gt=0)
    """로드할 캔들 수. BACKTEST 모드에서만 사용."""

    window_size: int = Field(default=50, gt=0)
    """Owl에게 전달할 슬라이딩 윈도우 크기 (최근 N 봉)."""


class TradeRecord(BaseModel):
    """단일 거래 기록 (In-memory, 리포트용)."""

    timestamp: str
    action: str
    price: float
    quantity: float
    fee: float
    cash_after: float
    equity_after: float
    reasoning: str


class BacktestResult(BaseModel):
    """백테스트 실행 결과."""

    session_id: str
    strategy_id: str
    symbol: str
    interval: str
    initial_cash: float
    final_cash: float
    final_equity: float
    equity_curve: list[float] = Field(default_factory=list)
    trade_records: list[TradeRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 포트폴리오 트랜잭션 헬퍼
# ---------------------------------------------------------------------------

def execute_buy(cash: float, price: float) -> tuple[float, float, float]:
    """전액 매수. (new_cash, quantity, fee) 반환."""
    fee = cash * FEE_RATE
    net_spend = cash - fee
    quantity = net_spend / price
    return 0.0, quantity, fee


def execute_sell(quantity: float, price: float) -> tuple[float, float, float]:
    """전량 매도. (new_cash, new_quantity, fee) 반환."""
    revenue = quantity * price
    fee = revenue * FEE_RATE
    net_revenue = revenue - fee
    return net_revenue, 0.0, fee


# ---------------------------------------------------------------------------
# 백테스트 엔진
# ---------------------------------------------------------------------------

class BacktestEngine:
    """백테스트 시뮬레이터.

    사용 예::

        engine = BacktestEngine()
        result = await engine.run(EngineConfig(
            symbol="KRW-BTC",
            style="balanced",
            user_prompt="비트코인 안정 매매",
        ))
    """

    # ------------------------------------------------------------------
    # 퍼블릭 진입점
    # ------------------------------------------------------------------

    async def run(self, config: EngineConfig) -> BacktestResult:
        session_id = f"bt-{uuid.uuid4().hex[:12]}"
        logger.info("=" * 60)
        logger.info("[Engine] 백테스트 세션 시작 — session=%s", session_id)
        logger.info("[Engine] %s | %s | %s", config.symbol, config.style, config.interval)
        logger.info("=" * 60)

        # ① Meerkat — 전략 설계
        strategy_id, strategy = await run_meerkat(
            user_prompt=config.user_prompt,
            symbol=config.symbol,
            style=config.style,
            session_id=session_id,
        )
        logger.info("[Engine] 전략 확보 — strategy_id=%s", strategy_id)

        # ② OHLCV 전체 데이터 로드
        candles = await fetch_ohlcv(config.symbol, config.interval, config.candle_count)
        if not candles:
            raise ValueError(f"OHLCV 데이터 없음: {config.symbol} {config.interval}")
        if len(candles) < config.window_size + 1:
            raise ValueError(
                f"캔들 수({len(candles)})가 윈도우 크기({config.window_size})보다 작습니다."
            )

        # ③ 가상 자산 초기화 (MongoAssetProvider)
        db = get_db()
        provider = await MongoAssetProvider.initialize_session(
            db=db,
            session_id=session_id,
            initial_cash=config.initial_cash,
        )

        # ④ 시뮬레이션 루프
        result = await self._simulate(
            config=config,
            session_id=session_id,
            strategy_id=strategy_id,
            strategy=strategy,
            candles=candles,
            provider=provider,
            db=db,
        )

        logger.info("[Engine] 백테스트 완료 — final_equity=%.2f", result.final_equity)
        return result

    # ------------------------------------------------------------------
    # 시뮬레이션 루프
    # ------------------------------------------------------------------

    async def _simulate(
        self,
        config: EngineConfig,
        session_id: str,
        strategy_id: str,
        strategy: dict,
        candles: list[dict],
        provider: MongoAssetProvider,
        db,
    ) -> BacktestResult:
        cash = config.initial_cash
        coin_qty = 0.0
        equity_curve: list[float] = []
        trade_records: list[TradeRecord] = []

        start_idx = config.window_size
        total_steps = len(candles) - start_idx

        print(f"\n{'='*60}")
        print(f"🔁 시뮬레이션 시작 — {total_steps}개 봉 처리")
        print(f"{'='*60}\n")

        for i in range(start_idx, len(candles)):
            current_candle = candles[i]
            window = candles[max(0, i - config.window_size + 1): i + 1]
            current_price = current_candle["close"]
            current_ts = current_candle["timestamp"]

            # Owl 의사결정
            decision: OwlDecision = await owl_decide(
                ohlcv_window=window,
                strategy=strategy,
                current_ts=current_ts,
            )

            fee = 0.0
            prev_cash, prev_qty = cash, coin_qty

            if decision.action == OwlAction.BUY and cash > 0:
                cash, coin_qty, fee = execute_buy(cash, current_price)
                print(
                    f"  🟢 BUY  [{current_ts[:10]}] "
                    f"price={current_price:,.0f}  qty={coin_qty:.6f}  fee={fee:,.0f}"
                )
            elif decision.action == OwlAction.SELL and coin_qty > 0:
                cash, coin_qty, fee = execute_sell(coin_qty, current_price)
                print(
                    f"  🔴 SELL [{current_ts[:10]}] "
                    f"price={current_price:,.0f}  cash={cash:,.0f}  fee={fee:,.0f}"
                )
            else:
                print(
                    f"  ⚪ HOLD [{current_ts[:10]}] "
                    f"price={current_price:,.0f}  cash={cash:,.0f}  qty={coin_qty:.6f}"
                )

            equity = cash + coin_qty * current_price
            equity_curve.append(equity)

            # TradeLog 저장 (HOLD 제외)
            if decision.action in (OwlAction.BUY, OwlAction.SELL):
                traded_qty = coin_qty if decision.action == OwlAction.BUY else prev_qty
                log = TradeLogDocument(
                    session_id=session_id,
                    strategy_id=strategy_id,
                    symbol=config.symbol,
                    action=TradeAction(decision.action.value.lower()),
                    price=current_price,
                    quantity=traded_qty,
                    fee=fee,
                    timestamp=datetime.fromisoformat(current_ts).replace(tzinfo=UTC),
                    reasoning=decision.reasoning,
                )
                await db[CollectionName.TRADE_LOGS].insert_one(log.model_dump(by_alias=True))

                trade_records.append(TradeRecord(
                    timestamp=current_ts,
                    action=decision.action.value,
                    price=current_price,
                    quantity=traded_qty,
                    fee=fee,
                    cash_after=cash,
                    equity_after=equity,
                    reasoning=decision.reasoning,
                ))

            # AssetState 스냅샷 저장
            holdings = (
                [Holding(symbol=config.symbol, quantity=coin_qty, avg_buy_price=current_price)]
                if coin_qty > 0 else []
            )
            await provider.save_snapshot(
                cash_balance=cash,
                holdings=holdings,
                total_value=equity,
                strategy_id=strategy_id,
                timestamp=datetime.fromisoformat(current_ts).replace(tzinfo=UTC),
            )

        final_equity = cash + coin_qty * candles[-1]["close"]

        return BacktestResult(
            session_id=session_id,
            strategy_id=strategy_id,
            symbol=config.symbol,
            interval=config.interval,
            initial_cash=config.initial_cash,
            final_cash=cash,
            final_equity=final_equity,
            equity_curve=equity_curve,
            trade_records=trade_records,
        )
