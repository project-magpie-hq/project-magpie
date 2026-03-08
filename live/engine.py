"""
LiveEngine — 실거래 모드 자동 매매 엔진.

BacktestEngine과 달리 과거 데이터를 순회하지 않는다.
매 캔들 종가 확정 시점까지 대기한 뒤 Owl의 판단을 받아 실주문을 실행한다.

흐름:
  1. Meerkat LangGraph 실행 → 전략 확보 (Backtest와 동일)
  2. UpbitAssetProvider로 실계좌 잔고 연결
  3. 무한 루프:
       a. 업비트 Open API → 최신 N 봉 로드
       b. Owl 판단 → BUY / SELL / HOLD
       c. 판단이 BUY/SELL이면 pyupbit 시장가 주문 실행
       d. MongoDB에 TradeLog + AssetState 기록
       e. 다음 봉 종가 확정 시점까지 대기
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from agents.owl_director.decision import OwlAction, OwlDecision, owl_decide
from backtest.engine import EngineConfig
from core.constants import FEE_RATE, INTERVAL_SECONDS
from core.graph import fetch_ohlcv, run_meerkat
from db.connection import get_db
from db.schemas import CollectionName, Holding, TradeAction, TradeLogDocument
from providers.mongo import MongoAssetProvider
from providers.upbit import UpbitAssetProvider

logger = logging.getLogger(__name__)


class LiveEngine:
    """실거래 모드 자동 매매 엔진.

    사용 예::

        engine = LiveEngine()
        await engine.run(EngineConfig(
            symbol="KRW-BTC",
            style="balanced",
            user_prompt="비트코인 균형 잡힌 매매",
            mode=ProviderMode.REAL,
            interval="minute60",
            window_size=50,
        ))
    """

    async def run(self, config: EngineConfig) -> None:
        """실거래 루프를 시작한다. Ctrl+C 로 중단할 수 있다."""
        session_id = f"live-{uuid.uuid4().hex[:12]}"

        logger.info("=" * 60)
        logger.info("[Live] 실거래 세션 시작 — session=%s", session_id)
        logger.info("[Live] %s | %s | %s", config.symbol, config.style, config.interval)
        logger.info("=" * 60)

        # ① Meerkat — 전략 확보
        strategy_id, strategy = await run_meerkat(
            user_prompt=config.user_prompt,
            symbol=config.symbol,
            style=config.style,
            session_id=session_id,
        )
        logger.info("[Live] 전략 확보 — strategy_id=%s", strategy_id)

        # ② 실계좌 Provider + DB 스냅샷 기록용 MongoProvider
        asset_provider = UpbitAssetProvider()
        db = get_db()
        mongo_provider = MongoAssetProvider(db=db, session_id=session_id)

        tick_seconds = INTERVAL_SECONDS.get(config.interval, 3_600)

        print(f"\n{'='*60}")
        print(f"🚀 실거래 루프 시작 — 봉 주기 {tick_seconds}s ({config.interval})")
        print("   Ctrl+C 로 안전하게 종료할 수 있습니다.")
        print(f"{'='*60}\n")

        try:
            await self._live_loop(
                config=config,
                session_id=session_id,
                strategy_id=strategy_id,
                strategy=strategy,
                asset_provider=asset_provider,
                mongo_provider=mongo_provider,
                db=db,
                tick_seconds=tick_seconds,
            )
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("[Live] 실거래 세션 종료 — session=%s", session_id)

    # ------------------------------------------------------------------
    # 실거래 루프
    # ------------------------------------------------------------------

    async def _live_loop(
        self,
        config: EngineConfig,
        session_id: str,
        strategy_id: str,
        strategy: dict,
        asset_provider: UpbitAssetProvider,
        mongo_provider: MongoAssetProvider,
        db,
        tick_seconds: int,
    ) -> None:
        while True:
            tick_start = datetime.now(UTC)
            current_ts = tick_start.isoformat()

            # (a) 최신 N 봉 로드
            window = await fetch_ohlcv(config.symbol, config.interval, config.window_size)
            if not window:
                logger.warning("[Live] OHLCV 로드 실패, 다음 봉까지 대기")
                await asyncio.sleep(tick_seconds)
                continue

            current_price = window[-1]["close"]

            # (b) Owl 판단
            decision: OwlDecision = await owl_decide(
                ohlcv_window=window,
                strategy=strategy,
                current_ts=current_ts,
            )

            logger.info(
                "[Live] Owl 판단 — %s (conf=%.2f) price=%.0f",
                decision.action.value, decision.confidence, current_price,
            )

            order_result = None
            fee = 0.0

            # (c) 실주문 실행
            portfolio = await asset_provider.get_portfolio()
            krw_balance = portfolio.cash
            coin_holding = next(
                (h for h in portfolio.holdings if h.symbol == config.symbol), None
            )
            coin_qty = coin_holding.quantity if coin_holding else 0.0

            if decision.action == OwlAction.BUY and krw_balance > 5_000:
                order_result = await asset_provider.buy_market_order(config.symbol, krw_balance)
                fee = krw_balance * FEE_RATE
                print(
                    f"  🟢 BUY  [{current_ts[:19]}] "
                    f"price={current_price:,.0f}  krw={krw_balance:,.0f}  fee={fee:,.0f}"
                )

            elif decision.action == OwlAction.SELL and coin_qty > 0:
                order_result = await asset_provider.sell_market_order(config.symbol, coin_qty)
                fee = coin_qty * current_price * FEE_RATE
                print(
                    f"  🔴 SELL [{current_ts[:19]}] "
                    f"price={current_price:,.0f}  qty={coin_qty:.8f}  fee={fee:,.0f}"
                )

            else:
                print(
                    f"  ⚪ HOLD [{current_ts[:19]}] "
                    f"price={current_price:,.0f}  krw={krw_balance:,.0f}  qty={coin_qty:.8f}"
                )

            # 주문 후 잔고 재조회 (최신 상태)
            await asyncio.sleep(2)   # 체결 대기
            portfolio_after = await asset_provider.get_portfolio()
            current_value = portfolio_after.total_value

            # (d) MongoDB 기록
            if decision.action in (OwlAction.BUY, OwlAction.SELL):
                log = TradeLogDocument(
                    session_id=session_id,
                    strategy_id=strategy_id,
                    symbol=config.symbol,
                    action=TradeAction(decision.action.value.lower()),
                    price=current_price,
                    quantity=krw_balance / current_price if decision.action == OwlAction.BUY else coin_qty,
                    fee=fee,
                    timestamp=tick_start,
                    reasoning=decision.reasoning,
                )
                await db[CollectionName.TRADE_LOGS].insert_one(log.model_dump(by_alias=True))

            holdings_snapshot = [
                Holding(
                    symbol=h.symbol,
                    quantity=h.quantity,
                    avg_buy_price=h.avg_buy_price,
                )
                for h in portfolio_after.holdings
            ]
            await mongo_provider.save_snapshot(
                cash_balance=portfolio_after.cash,
                holdings=holdings_snapshot,
                total_value=current_value,
                strategy_id=strategy_id,
                timestamp=tick_start,
            )

            # (e) 다음 봉까지 대기
            elapsed = (datetime.now(UTC) - tick_start).total_seconds()
            sleep_sec = max(0.0, tick_seconds - elapsed)
            logger.info("[Live] 다음 봉까지 %.0f 초 대기...", sleep_sec)
            await asyncio.sleep(sleep_sec)
