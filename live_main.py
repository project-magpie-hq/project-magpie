"""
live_main.py — 실거래(자동 매매) 실행 진입점.

사용법:
    uv run python live_main.py

설정:
    아래 CONFIG 블록에서 종목·스타일·봉 주기를 수정하세요.
    .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 가 반드시 설정되어 있어야 합니다.

⚠️  경고:
    이 스크립트를 실행하면 업비트 계정의 실제 자산으로 주문이 발생합니다.
    반드시 backtest_main.py 로 충분히 검증한 뒤 사용하세요.
"""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from backtest.engine import EngineConfig
from db.connection import close_connection, get_db
from db.schemas import ensure_indexes
from engine_factory import create_engine
from providers.base import ProviderMode

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ⚙️  실거래 설정 — 여기서 수정하세요
# ---------------------------------------------------------------------------
CONFIG = EngineConfig(
    symbol="KRW-BTC",
    style="balanced",
    user_prompt="비트코인 균형 잡힌 매매 전략",
    mode=ProviderMode.REAL,       # ← BACKTEST → REAL 로 전환
    interval="minute60",          # 실거래 봉 주기
    window_size=50,
    # initial_cash / candle_count 는 REAL 모드에서 무시됨
)
# ---------------------------------------------------------------------------


async def main() -> None:
    try:
        # ① MongoDB 인덱스 초기화
        db = get_db()
        await ensure_indexes(db)

        # ② 엔진 선택 (REAL → LiveEngine)
        engine = create_engine(CONFIG)
        logger.info("실거래 엔진 시작: %s (mode=%s)", type(engine).__name__, CONFIG.mode)

        # ③ 무한 루프 실행 (Ctrl+C 로 종료)
        await engine.run(CONFIG)
    finally:
        await close_connection()


if __name__ == "__main__":
    asyncio.run(main())
