import argparse
import asyncio
from typing import Any

import pandas as pd

from bat_daemon.integrations.target_refresh import invoke_graph_for_target_refresh
from bat_daemon.market_data.historical import estimate_historical_batches, fetch_historical_candles_by_range
from bat_daemon.run import BatDaemon
from bat_daemon.session_stats import build_session_stats_from_signal_history
from bat_daemon.utils.backtest import (
    BACKTEST_CANDLE_INTERVAL,
    BACKTEST_CLOSE_WINDOW_MINUTES,
    BACKTEST_REPLAY_MODES,
    DEFAULT_BACKTEST_REPLAY_MODE,
    BacktestProgressCallback,
    backtest_warmup_start,
    build_backtest_result,
    build_backtest_tick_row,
    build_rolling_window_candle,
    candle_replay_points,
    emit_backtest_event,
    format_candle_time,
    limit_tick_rows_for_report,
    load_backtest_universe,
    normalize_backtest_time,
    to_upbit_tick,
)
from magpie_agent.graphs.target_refresh import build_target_refresh_graph
from magpie_agent.tools.monitor_target import clear_monitoring_targets_by_user, fetch_monitoring_targets_by_user
from magpie_agent.tools.strategy import clone_strategy_to_user
from magpie_agent.tools.wallet import fetch_wallet_by_user, register_wallet


async def _load_historical_data(
    coins: set[str],
    load_start: str,
    replay_start: str,
    end: str,
    progress_callback: BacktestProgressCallback | None = None,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    historical_data: dict[str, pd.DataFrame] = {}
    missing_coins: list[str] = []
    for coin in sorted(coins):
        print(f"   - {coin} 1분 캔들 로드 중...")
        estimated_total_batches = estimate_historical_batches(load_start, end, interval=BACKTEST_CANDLE_INTERVAL)
        emit_backtest_event(
            progress_callback,
            "historical_coin_started",
            f"{coin} 1분 캔들 로드를 시작합니다.",
            coin=coin,
            candle_interval=BACKTEST_CANDLE_INTERVAL,
            estimated_total_batches=estimated_total_batches,
            load_start=load_start,
            replay_start=replay_start,
        )

        def on_batch(batch_count: int, oldest_candle_time: Any) -> None:
            if batch_count == 1 or batch_count % 25 == 0:
                emit_backtest_event(
                    progress_callback,
                    "historical_coin_progress",
                    f"{coin} 과거 캔들 로드 중... ({batch_count}/{estimated_total_batches or '?'} batch)",
                    coin=coin,
                    batch_count=batch_count,
                    estimated_total_batches=estimated_total_batches,
                    oldest_candle_time=str(oldest_candle_time),
                    candle_interval=BACKTEST_CANDLE_INTERVAL,
                )

        df = fetch_historical_candles_by_range(
            coin,
            load_start,
            end,
            interval=BACKTEST_CANDLE_INTERVAL,
            on_batch=on_batch,
        )
        replay_df = df[df.index >= pd.Timestamp(replay_start)] if not df.empty else df
        if replay_df.empty:
            print(f"     ⚠️ {coin}: 데이터 없음")
            missing_coins.append(coin)
            emit_backtest_event(
                progress_callback,
                "historical_coin_loaded",
                f"{coin} 백테스트 기간 과거 캔들 데이터가 없습니다.",
                coin=coin,
                candle_count=0,
                warmup_candle_count=len(df),
                candle_interval=BACKTEST_CANDLE_INTERVAL,
                estimated_total_batches=estimated_total_batches,
            )
            continue

        historical_data[coin] = df
        print(f"     ✅ 재생 {len(replay_df)}개 / 워밍업 포함 {len(df)}개 캔들")
        emit_backtest_event(
            progress_callback,
            "historical_coin_loaded",
            f"{coin} 1분 캔들 로드 완료 (재생 {len(replay_df)}개 / 워밍업 포함 {len(df)}개)",
            coin=coin,
            candle_count=len(replay_df),
            warmup_candle_count=len(df),
            candle_interval=BACKTEST_CANDLE_INTERVAL,
            estimated_total_batches=estimated_total_batches,
        )
    return historical_data, missing_coins


async def prepare_backtest_environment(
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    initial_balance: float,
    selected_target_coins: list[str] | None = None,
    progress_callback: BacktestProgressCallback | None = None,
) -> None:
    backtest_time = normalize_backtest_time(start)

    emit_backtest_event(
        progress_callback,
        "setup_started",
        "백테스트 환경 준비를 시작합니다.",
        strategy_user_id=strategy_user_id,
        backtest_id=backtest_id,
        start=start,
        initial_balance=initial_balance,
        selected_target_coins=selected_target_coins,
    )
    print("\n🧰 백테스트 전용 환경을 준비합니다...")
    await register_wallet(backtest_id, initial_balance)
    emit_backtest_event(
        progress_callback,
        "wallet_initialized",
        "백테스트 지갑을 초기화했습니다.",
        backtest_id=backtest_id,
        initial_balance=initial_balance,
    )
    cloned_strategy = await clone_strategy_to_user(
        strategy_user_id,
        backtest_id,
        target_coins_override=selected_target_coins,
    )
    emit_backtest_event(
        progress_callback,
        "strategy_cloned",
        "원본 전략을 백테스트용 전략으로 복제했습니다.",
        backtest_id=backtest_id,
        selected_target_coins=cloned_strategy.target_coins,
    )
    deleted_count = await clear_monitoring_targets_by_user(backtest_id)
    print(f"   🧹 기존 backtest monitoring target 삭제: {deleted_count}건")
    print(f"   🎯 이번 백테스트 대상 코인: {cloned_strategy.target_coins}")
    emit_backtest_event(
        progress_callback,
        "targets_cleared",
        "기존 백테스트 monitoring_targets를 정리했습니다.",
        deleted_count=deleted_count,
    )

    refresh_graph = build_target_refresh_graph()
    for target_coin in cloned_strategy.target_coins:
        emit_backtest_event(
            progress_callback,
            "initial_refresh_started",
            f"{target_coin} 초기 monitoring_target 생성을 위해 Target Refresh Graph를 실행합니다.",
            target_coin=target_coin,
            backtest_time=backtest_time,
            selected_target_coins=cloned_strategy.target_coins,
        )
        await invoke_graph_for_target_refresh(
            refresh_graph,
            backtest_id,
            target_coin=target_coin,
            backtest_time=backtest_time,
            prompt_message=(
                f"{target_coin}의 과거 시점 기준 백테스트를 시작합니다. 현재 전략, 지갑, 기존 타점을 참고해 "
                "새로운 waiting-buy 타점을 계산하고 저장하세요."
            ),
        )

    generated_targets = await fetch_monitoring_targets_by_user(backtest_id)
    if not generated_targets:
        raise RuntimeError("백테스트용 monitoring target 생성에 실패했습니다.")
    emit_backtest_event(
        progress_callback,
        "initial_refresh_completed",
        "초기 monitoring_target 생성이 완료되었습니다.",
        generated_target_count=len(generated_targets),
    )


async def collect_backtest_run(
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    end: str,
    initial_balance: float,
    selected_target_coins: list[str] | None = None,
    replay_mode: str = DEFAULT_BACKTEST_REPLAY_MODE,
    *,
    max_tick_rows: int | None = None,
    progress_callback: BacktestProgressCallback | None = None,
) -> dict[str, Any]:
    if replay_mode not in BACKTEST_REPLAY_MODES:
        raise ValueError(f"지원하지 않는 replay_mode 입니다: {replay_mode}")

    await prepare_backtest_environment(
        strategy_user_id,
        backtest_id,
        start,
        initial_balance,
        selected_target_coins=selected_target_coins,
        progress_callback=progress_callback,
    )

    bat = BatDaemon(
        backtest_id,
        wallet_user_id=backtest_id,
        dry_run=False,
        enable_graph=True,
        backtest_mode=True,
        event_callback=progress_callback,
    )
    await bat.load_targets_from_db_once()
    initial_targets = {coin: target.model_copy(deep=True) for coin, target in bat.active_targets.items()}
    emit_backtest_event(
        progress_callback,
        "initial_targets_loaded",
        "초기 monitoring_target을 메모리에 로드했습니다.",
        active_target_coins=sorted(initial_targets),
    )

    if not bat.watching_coins:
        return build_backtest_result(initial_targets, bat.active_targets, "monitoring target이 없습니다.")

    backtest_universe = await load_backtest_universe(backtest_id)
    load_start = backtest_warmup_start(start, window_minutes=BACKTEST_CLOSE_WINDOW_MINUTES)
    historical_data, missing_coins = await _load_historical_data(
        backtest_universe or bat.watching_coins,
        load_start,
        start,
        end,
        progress_callback=progress_callback,
    )
    emit_backtest_event(
        progress_callback,
        "historical_data_loaded",
        "과거 1분 캔들 로드가 완료되었습니다.",
        loaded_candles={coin: len(df) for coin, df in historical_data.items()},
        selected_target_coins=sorted(backtest_universe),
        candle_interval=BACKTEST_CANDLE_INTERVAL,
        replay_mode=replay_mode,
        missing_coins=missing_coins,
        load_start=load_start,
        replay_start=start,
    )
    if missing_coins:
        missing_coin_text = ", ".join(missing_coins)
        raise RuntimeError(
            f"백테스트 기간에 과거 캔들 데이터가 없는 코인이 있습니다: {missing_coin_text} / 기간: {start} ~ {end}"
        )
    if not historical_data:
        return build_backtest_result(initial_targets, bat.active_targets, "로드된 과거 캔들이 없습니다.")

    tick_rows: list[dict[str, Any]] = []
    processed_ticks = 0
    replay_start_ts = pd.Timestamp(start)
    timeline = sorted(ts for ts in set().union(*[df.index for df in historical_data.values()]) if ts >= replay_start_ts)
    total_tick_count = sum(
        len(candle_replay_points(df.loc[candle_time], replay_mode))
        for df in historical_data.values()
        for candle_time in df.index
    )
    emit_backtest_event(
        progress_callback,
        "replay_started",
        "과거 tick 재생을 시작합니다.",
        total_candles=len(timeline),
        total_ticks=total_tick_count,
        candle_interval=BACKTEST_CANDLE_INTERVAL,
        replay_mode=replay_mode,
    )

    for candle_time in timeline:
        candle_time_str = format_candle_time(candle_time)
        emit_backtest_event(
            progress_callback,
            "candle_started",
            f"{candle_time_str} 캔들 재생 중입니다.",
            candle_time=candle_time_str,
            active_coins=[coin for coin, df in historical_data.items() if candle_time in df.index],
        )
        for coin, df in historical_data.items():
            if candle_time not in df.index:
                continue

            candle = build_rolling_window_candle(df, candle_time)
            for _, trade_price in candle_replay_points(candle, replay_mode):
                tick = to_upbit_tick(coin, candle_time, candle, trade_price)
                target_before = bat.active_targets[coin].model_copy(deep=True) if coin in bat.active_targets else None
                signal_count_before = len(bat.signal_history)
                await bat.process_candle_tick(coin, tick)
                if bat.refresh_task is not None:
                    await bat.wait_for_refresh_completion()
                target_after = bat.active_targets.get(coin)
                new_signals = bat.signal_history[signal_count_before:]
                processed_ticks += 1
                tick_row = build_backtest_tick_row(coin, tick, target_before, target_after, new_signals, "backtest")

                emit_backtest_event(
                    progress_callback,
                    "tick_processed",
                    f"{coin} tick 처리 완료",
                    coin=coin,
                    candle_time=candle_time_str,
                    price=trade_price,
                    processed_ticks=processed_ticks,
                    total_ticks=total_tick_count,
                    status_before=str(target_before.status) if target_before else None,
                    status_after=str(target_after.status) if target_after else None,
                    signal_count=len(new_signals),
                    tick_row=tick_row,
                )

                tick_rows.append(tick_row)

    await bat.flush_current_candles()
    await bat.wait_for_refresh_completion()
    emit_backtest_event(
        progress_callback,
        "replay_completed",
        "과거 tick 재생이 완료되었습니다.",
        processed_ticks=processed_ticks,
        signal_count=len(bat.signal_history),
        final_target_coins=sorted(bat.active_targets),
    )

    return {
        "initial_targets": initial_targets,
        "final_targets": bat.active_targets,
        "tick_rows": limit_tick_rows_for_report(tick_rows, max_tick_rows),
        "signals": bat.signal_history,
        "session_stats": build_session_stats_from_signal_history(bat.signal_history),
        "processed_ticks": processed_ticks,
        "loaded_candles": {coin: len(df) for coin, df in historical_data.items()},
        "wallet": await fetch_wallet_by_user(backtest_id),
        "wallet_user_id": backtest_id,
        "strategy_user_id": strategy_user_id,
        "backtest_id": backtest_id,
        "selected_target_coins": sorted(backtest_universe),
        "generated_targets": await fetch_monitoring_targets_by_user(backtest_id),
    }


async def run_backtest(
    strategy_user_id: str,
    backtest_id: str,
    start: str,
    end: str,
    initial_balance: float,
    selected_target_coins: list[str] | None = None,
    replay_mode: str = DEFAULT_BACKTEST_REPLAY_MODE,
    progress_callback: BacktestProgressCallback | None = None,
) -> None:
    print("=" * 60)
    print("🧪 Project Magpie: Bat 백테스트 시작")
    print(f"📋 strategy_user_id: {strategy_user_id}")
    print(f"🧪 backtest_id: {backtest_id}")
    print(f"👛 initial_balance: {initial_balance:,.0f}")
    print(f"📅 기간: {start} ~ {end}")
    if selected_target_coins is not None:
        print(f"🎯 선택 코인: {', '.join(selected_target_coins)}")
    print(f"⏱️ 백테스트 캔들: 1분 / 재생 모드: {replay_mode}")
    print("=" * 60)
    print("\n▶️ 과거 캔들 재생을 시작합니다.")
    print("   run.py와 동일한 체결 경로를 사용하며, 차이는 과거 tick 데이터를 재생한다는 점뿐입니다.\n")

    result = await collect_backtest_run(
        strategy_user_id,
        backtest_id,
        start,
        end,
        initial_balance,
        selected_target_coins,
        replay_mode,
        progress_callback=progress_callback,
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
    parser = argparse.ArgumentParser(description="전략을 backtest_id로 복제해 과거 업비트 1분 캔들로 재생합니다.")
    parser.add_argument("--strategy-user-id", required=True, help="원본 strategies를 복사할 user_id")
    parser.add_argument(
        "--backtest-id", required=True, help="백테스트 전용 strategies/wallets/targets를 저장할 user_id"
    )
    parser.add_argument("--start", required=True, help="시작 일시. 예: '2026-06-01 00:00:00'")
    parser.add_argument("--end", required=True, help="종료 일시. 예: '2026-07-01 00:00:00'")
    parser.add_argument("--initial-balance", type=float, default=100000000.0, help="백테스트 지갑 초기 KRW")
    parser.add_argument(
        "--replay-mode",
        choices=BACKTEST_REPLAY_MODES,
        default=DEFAULT_BACKTEST_REPLAY_MODE,
        help="1분 캔들을 어떤 방식으로 재생할지 선택. 기본값: close_only",
    )
    parser.add_argument(
        "--target-coins",
        nargs="+",
        help="백테스트에 사용할 target_coins 일부 선택. 생략 시 원본 전략의 전체 target_coins 사용",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_backtest(
        args.strategy_user_id,
        args.backtest_id,
        args.start,
        args.end,
        args.initial_balance,
        args.target_coins,
        args.replay_mode,
    )


if __name__ == "__main__":
    asyncio.run(main())
