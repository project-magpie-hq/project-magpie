import argparse
import asyncio
from typing import Any

import pandas as pd

from bat_daemon.integrations.target_refresh import invoke_graph_for_target_refresh
from bat_daemon.market_data.historical import fetch_historical_candles_by_range
from bat_daemon.run import BatDaemon
from bat_daemon.session_stats import build_session_stats_from_signal_history
from magpie_agent.graphs.target_refresh import build_target_refresh_graph
from magpie_agent.tools.monitor_target import clear_monitoring_targets_by_user, fetch_monitoring_targets_by_user
from magpie_agent.tools.strategy import clone_strategy_to_user, fetch_strategy_by_user
from magpie_agent.tools.wallet import fetch_wallet_by_user, register_wallet


def _format_candle_time(index: pd.Timestamp) -> str:
    return index.strftime("%Y-%m-%dT%H:%M:%S")


def _normalize_backtest_time(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%S")


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


async def _load_backtest_universe(backtest_id: str) -> set[str]:
    strategy = await fetch_strategy_by_user(backtest_id)
    if strategy is None:
        return set()
    return set(strategy.get("target_coins") or [])


async def prepare_backtest_environment(
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    initial_balance: float,
) -> None:
    backtest_time = _normalize_backtest_time(start)

    print("\n🧰 백테스트 전용 환경을 준비합니다...")
    await register_wallet(backtest_id, initial_balance)
    await clone_strategy_to_user(strategy_user_id, backtest_id)
    deleted_count = await clear_monitoring_targets_by_user(backtest_id)
    print(f"   🧹 기존 backtest monitoring target 삭제: {deleted_count}건")

    refresh_graph = build_target_refresh_graph()
    await invoke_graph_for_target_refresh(
        refresh_graph,
        backtest_id,
        backtest_time=backtest_time,
        prompt_message=(
            "과거 시점 기준 백테스트를 시작합니다. 현재 전략, 지갑, 기존 타점을 참고해 "
            "새로운 waiting-buy 타점을 계산하고 저장하세요."
        ),
    )

    generated_targets = await fetch_monitoring_targets_by_user(backtest_id)
    if not generated_targets:
        raise RuntimeError("백테스트용 monitoring target 생성에 실패했습니다.")


def build_backtest_tick_row(
    coin: str,
    tick: dict[str, Any],
    target_before,
    target_after,
    signals: list[dict[str, Any]],
    source: str = "backtest",
) -> dict[str, Any]:
    target_for_thresholds = target_before or target_after
    row = {
        "source": source,
        "coin": coin,
        "candle_time": tick.get("candle_date_time_kst"),
        "trade_price": tick.get("trade_price"),
        "opening_price": tick.get("opening_price"),
        "high_price": tick.get("high_price"),
        "low_price": tick.get("low_price"),
        "volume": tick.get("candle_acc_trade_volume"),
        "status_before": str(target_before.status) if target_before else None,
        "status_after": str(target_after.status) if target_after else None,
        "signal": ", ".join(signal.get("signal_type", "") for signal in signals) or None,
        "event_reason": ", ".join(signal.get("event_reason", "") for signal in signals) or None,
        "executed_volume": ", ".join(str(signal.get("executed_volume", "")) for signal in signals) or None,
    }
    if target_for_thresholds:
        row.update(
            {
                "trigger": str(target_for_thresholds.trigger_basis),
                "buy_lower": target_for_thresholds.buy_price_lower_limit,
                "buy_upper": target_for_thresholds.buy_price_upper_limit,
                "buy_allocation_pct": target_for_thresholds.buy_allocation_pct,
                "take_profit": target_for_thresholds.take_profit_price,
                "stop_loss": target_for_thresholds.stop_loss_price,
            }
        )
    return row


def build_backtest_result(
    initial_targets: dict[str, Any],
    final_targets: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    return {
        "initial_targets": initial_targets,
        "final_targets": final_targets,
        "tick_rows": [],
        "signals": [],
        "session_stats": None,
        "processed_ticks": 0,
        "error": error,
        "wallet": None,
        "wallet_user_id": None,
        "strategy_user_id": None,
        "backtest_id": None,
        "generated_targets": None,
        "loaded_candles": {},
    }


async def collect_backtest_run(
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    end: str,
    initial_balance: float,
    *,
    max_tick_rows: int | None = None,
) -> dict[str, Any]:
    await prepare_backtest_environment(strategy_user_id, backtest_id, start, initial_balance)

    bat = BatDaemon(
        backtest_id,
        wallet_user_id=backtest_id,
        dry_run=False,
        enable_graph=True,
        backtest_mode=True,
    )
    await bat.load_targets_from_db_once()
    initial_targets = {coin: target.model_copy(deep=True) for coin, target in bat.active_targets.items()}

    if not bat.watching_coins:
        return build_backtest_result(initial_targets, bat.active_targets, "monitoring target이 없습니다.")

    backtest_universe = await _load_backtest_universe(backtest_id)
    historical_data = await _load_historical_data(backtest_universe or bat.watching_coins, start, end)
    if not historical_data:
        return build_backtest_result(initial_targets, bat.active_targets, "로드된 과거 캔들이 없습니다.")

    tick_rows: list[dict[str, Any]] = []
    processed_ticks = 0
    timeline = sorted(set().union(*[df.index for df in historical_data.values()]))

    for candle_time in timeline:
        for coin, df in historical_data.items():
            if candle_time not in df.index:
                continue

            candle = df.loc[candle_time]
            for _, trade_price in _candle_path(candle):
                tick = _to_upbit_tick(coin, candle_time, candle, trade_price)
                target_before = bat.active_targets[coin].model_copy(deep=True) if coin in bat.active_targets else None
                signal_count_before = len(bat.signal_history)
                await bat.process_candle_tick(coin, tick)
                if bat.refresh_task is not None:
                    await bat.wait_for_refresh_completion()
                target_after = bat.active_targets.get(coin)
                new_signals = bat.signal_history[signal_count_before:]
                processed_ticks += 1

                if max_tick_rows is None or len(tick_rows) < max_tick_rows or new_signals:
                    tick_rows.append(
                        build_backtest_tick_row(coin, tick, target_before, target_after, new_signals, "backtest")
                    )

    await bat.flush_current_candles()
    await bat.wait_for_refresh_completion()

    return {
        "initial_targets": initial_targets,
        "final_targets": bat.active_targets,
        "tick_rows": tick_rows,
        "signals": bat.signal_history,
        "session_stats": build_session_stats_from_signal_history(bat.signal_history),
        "processed_ticks": processed_ticks,
        "loaded_candles": {coin: len(df) for coin, df in historical_data.items()},
        "wallet": await fetch_wallet_by_user(backtest_id),
        "wallet_user_id": backtest_id,
        "strategy_user_id": strategy_user_id,
        "backtest_id": backtest_id,
        "generated_targets": await fetch_monitoring_targets_by_user(backtest_id),
    }


async def run_backtest(
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    end: str,
    initial_balance: float,
) -> None:
    print("=" * 60)
    print("🧪 Project Magpie: Bat 백테스트 시작")
    print(f"📋 strategy_user_id: {strategy_user_id}")
    print(f"🧪 backtest_id: {backtest_id}")
    print(f"👛 initial_balance: {initial_balance:,.0f}")
    print(f"📅 기간: {start} ~ {end}")
    print("=" * 60)
    print("\n▶️ 과거 캔들 재생을 시작합니다.")
    print("   run.py와 동일한 체결 경로를 사용하며, 차이는 과거 tick 데이터를 재생한다는 점뿐입니다.\n")

    result = await collect_backtest_run(
        strategy_user_id,
        backtest_id,
        start,
        end,
        initial_balance,
    )

    if result.get("error"):
        print(f"❌ {result['error']}")
        return

    print("\n🏁 백테스트 종료")
    print(f"   처리한 가상 틱: {result.get('processed_ticks', 0):,}개")
    print(f"   감지된 신호: {len(result.get('signals', [])):,}개")

    final_wallet = result.get("wallet")
    if final_wallet is not None:
        print(f"   최종 백테스트 지갑 잔고: {final_wallet.balance:,.0f} KRW")
        print(f"   누적 체결 이력: {len(final_wallet.trade_history):,}건")

    if not result.get("signals"):
        print("   조건을 만족한 매수/매도 신호가 없습니다.")
        return

    print("\n📋 신호 내역")
    for signal in result["signals"]:
        print(
            f"   - [{signal.get('event_time')}] {signal['target_coin']} {signal['signal_type']} "
            f"@ {signal['price']:,.0f}원 ({signal['event_reason']}) -> {signal.get('result_status', '-')}"
            f" / volume={signal.get('executed_volume', '-')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="전략을 backtest_id로 복제해 과거 업비트 1시간 캔들로 재생합니다.")
    parser.add_argument("--strategy-user-id", required=True, help="원본 strategies를 복사할 user_id")
    parser.add_argument("--backtest-id", required=True, help="백테스트 전용 strategies/wallets/targets를 저장할 user_id")
    parser.add_argument("--start", required=True, help="시작 일시. 예: '2024-01-01 00:00:00'")
    parser.add_argument("--end", required=True, help="종료 일시. 예: '2024-02-01 00:00:00'")
    parser.add_argument("--initial-balance", type=float, default=100000000.0, help="백테스트 지갑 초기 KRW")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_backtest(
        args.strategy_user_id,
        args.backtest_id,
        args.start,
        args.end,
        args.initial_balance,
    )


if __name__ == "__main__":
    asyncio.run(main())
