"""
backtest_main.py — 백테스트 실행 진입점.

사용법:
    uv run python backtest_main.py

설정:
    아래 CONFIG 블록에서 종목, 스타일, 사용자 요청을 수정하세요.
"""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from backtest.engine import BacktestEngine, EngineConfig
from backtest.reporter import BacktestReporter
from db.connection import close_connection, get_db
from db.schemas import ensure_indexes
from tools.db import update_strategy_performance

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ⚙️  백테스트 설정 — 여기서 수정하세요
# ---------------------------------------------------------------------------
CONFIG = EngineConfig(
    symbol="KRW-BTC",          # 업비트 마켓 코드
    style="balanced",           # 'aggressive' | 'stable' | 'balanced'
    user_prompt="비트코인 균형 잡힌 매매 전략",  # Meerkat에게 전달되는 원본 요청
    initial_cash=10_000_000.0,  # 초기 자본 (KRW 단위 — 1,000만 원)
    interval="day",             # 봉 단위 ('day' | 'minute60' 등)
    candle_count=30,           # 로드할 봉 수
    window_size=10,             # Owl에게 전달할 슬라이딩 윈도우 크기
)
# ---------------------------------------------------------------------------


async def main() -> None:
    try:
        # ① MongoDB 인덱스 초기화
        db = get_db()
        await ensure_indexes(db)
        logger.info("MongoDB 인덱스 초기화 완료")

        # ② 백테스트 실행
        engine = BacktestEngine()
        result = await engine.run(CONFIG)

        # ③ KPI 리포트 출력
        reporter = BacktestReporter(result)
        reporter.print_report()

        # ④ MongoDB 전략 성과 업데이트
        kpis = reporter.return_kpis()
        await update_strategy_performance.ainvoke({
            "strategy_id":  result.strategy_id,
            "profit_rate":  kpis["profit_rate"],
            "win_rate":     kpis["win_rate"],
            "sharpe_ratio": kpis["sharpe_ratio"],
            "max_drawdown": kpis["max_drawdown"],
            "total_trades": kpis["total_trades"],
        })
        logger.info("전략 성과 지표가 MongoDB에 기록되었습니다.")
    finally:
        await close_connection()


if __name__ == "__main__":
    asyncio.run(main())
