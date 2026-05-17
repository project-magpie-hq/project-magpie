import argparse
import asyncio
from typing import Any

import pandas as pd

from bat_daemon.market_data.historical import fetch_historical_candles_by_range
from bat_daemon.run import BatDaemon


def _format_candle_time(index: pd.Timestamp) -> str:
    return index.strftime("%Y-%m-%dT%H:%M:%S")


def _candle_path(candle: pd.Series) -> list[tuple[str, float]]:
    open_price = float(candle["open"])
    high_price = float(candle["high"])
    low_price = float(candle["low"])
    close_price = float(candle["close"])

    if close_price >= open_price:
        path = [("open", open_price), ("low", low_price), ("high", high_price), ("close", close_price)]
    else:
        path = [("open", open_price), ("high", high_price), ("low", low_price), ("close", close_price)]

    deduped_path: list[tuple[str, float]] = []
    for point_name, price in path:
        if not deduped_path or deduped_path[-1][1] != price:
            deduped_path.append((point_name, price))
    return deduped_path


def _to_upbit_tick(coin: str, candle_time: pd.Timestamp, candle: pd.Series, trade_price: float) -> dict[str, Any]:
    return {
        "code": coin,
        "candle_date_time_kst": _format_candle_time(candle_time),
        "opening_price": float(candle["open"]),
        "high_price": float(candle["high"]),
        "low_price": float(candle["low"]),
        "trade_price": trade_price,
        "candle_acc_trade_volume": float(candle["volume"]),
        "candle_acc_trade_price": float(candle.get("value", 0.0)),
    }


async def _load_historical_data(coins: set[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    historical_data: dict[str, pd.DataFrame] = {}
    for coin in sorted(coins):
        print(f"   - {coin} 1시간 캔들 로드 중...")
        df = fetch_historical_candles_by_range(coin, start, end)
        if df.empty:
            print(f"     ⚠️ {coin}: 데이터 없음")
            continue

        historical_data[coin] = df
        print(f"     ✅ {len(df)}개 캔들")
    return historical_data


async def run_backtest(user_id: str, start: str, end: str) -> None:
    bat = BatDaemon(user_id, dry_run=True, enable_graph=False)

    print("=" * 60)
    print("🧪 Project Magpie: Bat 백테스트 시작")
    print(f"👤 user_id: {user_id}")
    print(f"📅 기간: {start} ~ {end}")
    print("=" * 60)

    await bat.load_targets_from_db_once()
    if not bat.watching_coins:
        print("❌ DB에 monitoring target이 없어 백테스트를 중단합니다.")
        return

    print(f"🎯 DB 타겟: {sorted(bat.watching_coins)}")
    historical_data = await _load_historical_data(bat.watching_coins, start, end)
    if not historical_data:
        print("❌ 로드된 과거 캔들이 없어 백테스트를 중단합니다.")
        return

    timeline = sorted(set().union(*[df.index for df in historical_data.values()]))
    print("\n▶️ 과거 캔들 재생을 시작합니다.")
    print("   가정: 양봉은 open→low→high→close, 음봉은 open→high→low→close 순서로 체결 여부를 검사합니다.\n")

    processed_ticks = 0
    for candle_time in timeline:
        for coin, df in historical_data.items():
            if candle_time not in df.index:
                continue

            candle = df.loc[candle_time]
            for _, trade_price in _candle_path(candle):
                await bat.process_candle_tick(coin, _to_upbit_tick(coin, candle_time, candle, trade_price))
                processed_ticks += 1

    await bat.flush_current_candles()

    print("\n🏁 백테스트 종료")
    print(f"   처리한 가상 틱: {processed_ticks:,}개")
    print(f"   감지된 신호: {len(bat.signal_history):,}개")

    if not bat.signal_history:
        print("   조건을 만족한 매수/매도 신호가 없습니다.")
        return

    print("\n📋 신호 내역")
    for signal in bat.signal_history:
        print(
            f"   - [{signal.get('event_time')}] {signal['target_coin']} {signal['signal_type']} "
            f"@ {signal['price']:,.0f}원 ({signal['event_reason']}) -> {signal.get('result_status', '-')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DB monitoring target을 과거 업비트 1시간 캔들로 백테스트합니다.")
    parser.add_argument("--user-id", default="test_developer_001", help="monitoring_targets를 조회할 user_id")
    parser.add_argument("--start", required=True, help="시작 일시. 예: '2024-01-01 00:00:00'")
    parser.add_argument("--end", required=True, help="종료 일시. 예: '2024-02-01 00:00:00'")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_backtest(args.user_id, args.start, args.end)


if __name__ == "__main__":
    asyncio.run(main())
