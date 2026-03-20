import asyncio
import os

import pandas as pd

from db.mongo import strategies_collection
from simulator.constants import DEFAULT_STRATEGY, MARKET_PHASES
from simulator.data_loader import fetch_historical_candles_by_range
from simulator.engine import TimeMachineSimulator


async def fetch_active_strategy_from_db() -> dict:
    """MongoDB에서 현재 유저의 가장 최신 활성 전략을 가져옵니다."""
    print("🗄️ [DB]: 현재 활성화된 라이브 전략을 불러오는 중...")

    strategy_doc = await strategies_collection.find_one({"user_id": "test_developer_001", "state": "ACTIVE"})

    if strategy_doc and "strategy_details" in strategy_doc and "target_coins" in strategy_doc:
        print("   ✅ 전략 로드 성공!")
        return {
            "target_coins": strategy_doc["target_coins"],
            "strategy_details": strategy_doc["strategy_details"]
        }

    print("   ⚠️ 활성화된 전략이 없습니다. 임시 기본 전략으로 폴백합니다.")
    return DEFAULT_STRATEGY


async def load_mock_data(target_coins: list[str], phase_info: dict) -> dict[str, pd.DataFrame]:
    """시뮬레이션에 필요한 데이터를 로드합니다."""
    mock_data_map = {}
    for coin in target_coins:
        print(f"   - {coin} 1시간 캔들 수집 중...")
        df = fetch_historical_candles_by_range(coin, phase_info["start"], phase_info["end"])
        if not df.empty:
            mock_data_map[coin] = df
            print(f"     ✅ {len(df)}개의 캔들 로드 완료")
        else:
            print(f"     ❌ {coin} 데이터 로드 실패")
    return mock_data_map


async def main():
    # 환경 변수에서 현재 페이즈 읽기 (기본값은 SIDEWAYS)
    current_phase_key = os.getenv("MARKET_PHASE", "SIDEWAYS")
    phase_info = MARKET_PHASES.get(current_phase_key, MARKET_PHASES["SIDEWAYS"])

    print("=" * 60)
    print(f"🌍 시뮬레이터 환경: {current_phase_key} - {phase_info['desc']}")
    print(f"📅 기간: {phase_info['start']} ~ {phase_info['end']}")
    print("=" * 60)

    initial_strategy = await fetch_active_strategy_from_db()
    target_coins = initial_strategy["target_coins"]
    mock_data_map = await load_mock_data(target_coins, phase_info)

    if not mock_data_map:
        print("❌ 로드된 데이터가 없어 시뮬레이션을 중단합니다.")
        return

    print("✅ 모든 데이터 로딩 완료!\n")

    simulator = TimeMachineSimulator(mock_data_map, initial_strategy)
    await simulator.run_simulation()


if __name__ == "__main__":
    asyncio.run(main())
