import asyncio
import logging
from typing import Any

from websockets.exceptions import ConnectionClosed

from bat_daemon.constant import DB_SYNC_INTERVAL_SECONDS, SignalType
from bat_daemon.integrations.target_refresh import invoke_graph_for_target_refresh
from bat_daemon.market_data.candle import CandleTick, ClosedCandle, is_new_candle, parse_closed_candle, parse_tick
from bat_daemon.market_data.upbit_ws import connect_upbit_ws, receive_candle_tick, subscribe_candles
from bat_daemon.signals.rules import close_buy_rejection_reason, is_touch_buy_signal, should_check_close_buy
from bat_daemon.stores.target_store import fetch_target_map, fetch_targets_by_status, update_target_status
from db.entity import TargetEntity, WalletEntity
from magpie_agent.agents.meerkat_scanner.schema import TargetStatus
from magpie_agent.graphs.target_refresh import build_target_refresh_graph
from magpie_agent.tools.wallet import (
    apply_trade_to_wallet_entity,
    execute_trade_for_daemon,
    fetch_wallet_by_user,
    resolve_trade_volume_from_wallet,
)

logger = logging.getLogger(__name__)


class BatDaemon:
    def __init__(
        self,
        user_id: str,
        *,
        wallet_user_id: str | None = None,
        dry_run: bool = False,
        enable_graph: bool = True,
        backtest_mode: bool = False,
    ) -> None:
        self.user_id = user_id
        self.wallet_user_id = wallet_user_id or user_id
        self.dry_run = dry_run
        self.enable_graph = enable_graph
        self.backtest_mode = backtest_mode
        self.active_targets: dict[str, TargetEntity] = {}
        self.watching_coins: set[str] = set()
        self.ws_connection: Any = None
        self.current_candles: dict[str, dict[str, Any]] = {}
        self.refresh_graph = build_target_refresh_graph() if enable_graph and not dry_run else None
        self.refresh_task: asyncio.Task | None = None
        self.signal_history: list[dict[str, Any]] = []
        self.current_event_time: str | None = None
        self.simulated_wallet: WalletEntity | None = None
        self.current_trigger_info: dict | None = None

    async def run(self) -> None:
        await asyncio.gather(self.sync_targets_from_db(), self.listen_upbit_ws())

    # DB sync loop
    async def sync_targets_from_db(self) -> None:
        """MongoDB 타겟을 주기적으로 새로고침하고 감시 목록 변경을 반영합니다."""
        print("🦇 [Bat Daemon]: 감시 레이더 시작! MongoDB와 동기화를 시작합니다.")
        while True:
            # DB를 기준으로 현재 감시 대상을 다시 읽고, 변경이 있으면 웹소켓 재연결을 유도합니다.
            try:
                old_watching_coins = set(self.watching_coins)
                await self.load_targets_from_db_once()
                await self._maybe_schedule_expired_target_refresh()

                if self.watching_coins != old_watching_coins:
                    print(
                        f"   🔄 [DB 동기화]: 감시 대상 코인 변경 감지 -> 기존: {old_watching_coins} / 변경: {self.watching_coins}"
                    )
                    if self.ws_connection:
                        try:
                            await self.ws_connection.close()
                        except Exception as e:
                            logger.warning("[WebSocket 종료 에러]: %s", e)
                            print(f"   ❌ [WebSocket 종료 에러]: {e}")
            except Exception as e:
                logger.exception("[DB 동기화 에러]")
                print(f"   ❌ [DB 에러]: {e}")

            await asyncio.sleep(DB_SYNC_INTERVAL_SECONDS)

    async def load_targets_from_db_once(self) -> None:
        """MongoDB에 저장된 현재 모니터링 타겟을 한 번 로드합니다."""
        target_map = await fetch_target_map(self.user_id)
        self.active_targets = {
            coin: target
            for coin, target in target_map.items()
            if target.status in {TargetStatus.WAITING_BUY, TargetStatus.HOLDING}
        }
        self.watching_coins = set(self.active_targets)
        if self.dry_run and self.simulated_wallet is None:
            self.simulated_wallet = await fetch_wallet_by_user(self.wallet_user_id)

    # WebSocket loop
    async def listen_upbit_ws(self) -> None:
        """업비트 웹소켓에 연결하여 1시간 캔들 데이터를 실시간으로 수신하고 타점을 검사합니다."""
        while True:
            # 아직 감시 대상이 없으면 DB 동기화 루프가 대상을 채울 때까지 기다립니다.
            if not self.watching_coins:
                await asyncio.sleep(DB_SYNC_INTERVAL_SECONDS)
                continue

            try:
                async with connect_upbit_ws() as websocket:
                    self.ws_connection = websocket

                    await subscribe_candles(websocket, self.user_id, self.watching_coins)
                    print(f"\n📡 [WebSocket]: {list(self.watching_coins)} 1시간 캔들 스트림 수신 시작...\n")

                    while True:
                        coin, tick = await receive_candle_tick(websocket)
                        if coin:
                            await self.process_candle_tick(coin, tick)
            except ConnectionClosed as e:
                print(
                    f"   ⚠️ [WebSocket]: 연결 종료(사유: {e}). 코인 목록 변경이거나 네트워크 이슈입니다. 재연결을 시도합니다..."
                )
            except Exception as e:
                logger.exception("[WebSocket 에러]")
                print(f"   ❌ [WebSocket 에러]: {e}")
                await asyncio.sleep(2)

    # Candle / signal evaluation
    async def process_candle_tick(self, coin: str, tick: dict[str, Any]) -> None:
        """웹소켓으로 들어오는 실시간 캔들 조각을 받아 처리하는 메인 허브"""
        target = self.active_targets.get(coin)
        if not target:
            return

        parsed_tick = parse_tick(coin, tick)
        if parsed_tick is None:
            return

        self.current_event_time = parsed_tick.candle_time
        await self._check_realtime_signals(parsed_tick, target)

        last_candle = self.current_candles.get(coin)
        if is_new_candle(last_candle, parsed_tick.candle_time) and last_candle:
            print(
                f"\n⏰ [캔들 마감 감지]: {coin}의 {last_candle['candle_date_time_kst']} 캔들 마감. CLOSE 조건 판독 시작."
            )
            await self._evaluate_closed_candle(coin, last_candle, target)

        self.current_candles[coin] = tick

    async def flush_current_candles(self) -> None:
        """현재 메모리에 남아 있는 마지막 캔들을 마감 캔들로 평가합니다."""
        for coin, last_candle in list(self.current_candles.items()):
            target = self.active_targets.get(coin)
            if target:
                await self._evaluate_closed_candle(coin, last_candle, target)

    async def wait_for_refresh_completion(self) -> None:
        """예약된 타점 재계산 task가 있으면 종료될 때까지 기다립니다."""
        if self.refresh_task is None:
            return

        try:
            await self.refresh_task
        finally:
            self.refresh_task = None

    async def _check_realtime_signals(self, tick: CandleTick, target_entity: TargetEntity) -> None:
        """실시간(TOUCH) 조건 판별: 손절, 익절, TOUCH 방식의 매수"""
        if target_entity.status == TargetStatus.HOLDING:
            await self._check_exit_signal(tick, target_entity)
            return

        if is_touch_buy_signal(tick.current_price, target_entity):
            print(f"🚀 [BUY SIGNAL - TOUCH] {tick.coin} 매수 영역 진입! (현재가: {tick.current_price:,.0f}원)")
            await self._emit_signal(target_entity, SignalType.BUY, tick.current_price, "touch_entry_hit")

    async def _evaluate_closed_candle(self, coin: str, closed_candle: dict[str, Any], target_entity: TargetEntity):
        """방금 마감된 온전한 1시간 캔들을 기반으로 유효성 및 CLOSE 조건을 판별"""
        if not should_check_close_buy(target_entity):
            return

        parsed_candle = parse_closed_candle(closed_candle)
        if parsed_candle is None:
            logger.warning("[%s] 마감 캔들 데이터 누락 (close/open/volume)", coin)
            return

        if not self._passes_close_buy_conditions(coin, parsed_candle, target_entity):
            return

        print(
            f"🚀 [BUY SIGNAL - CLOSE] {coin} 1시간 캔들 마감 조건 완벽 충족! (종가: {parsed_candle.close_price:,.0f}원)"
        )
        await self._emit_signal(target_entity, SignalType.BUY, parsed_candle.close_price, "close_entry_hit")

    async def _check_exit_signal(self, tick: CandleTick, target_entity: TargetEntity) -> None:
        if tick.current_price >= target_entity.take_profit_price:
            print(f"💰 [PROFIT SIGNAL] {tick.coin} 익절가 돌파! (현재가: {tick.current_price:,.0f}원)")
            await self._emit_signal(target_entity, SignalType.SELL, tick.current_price, "take_profit_hit")
        elif tick.current_price <= target_entity.stop_loss_price:
            print(f"🩸 [STOP LOSS SIGNAL] {tick.coin} 손절선 붕괴! 비상 탈출! (현재가: {tick.current_price:,.0f}원)")
            await self._emit_signal(target_entity, SignalType.SELL, tick.current_price, "stop_loss_hit")

    def _passes_close_buy_conditions(self, coin: str, closed_candle: ClosedCandle, target_entity: TargetEntity) -> bool:
        rejection_reason = close_buy_rejection_reason(closed_candle, target_entity)

        if rejection_reason == "price_out_of_range":
            return False

        if rejection_reason == "volume_too_low":
            print(f"   ⏸️ [조건 미달] {coin}: 1시간 거래량({closed_candle.volume:,.0f})이 최소 기준에 미달합니다.")
            return False

        if rejection_reason == "not_bullish":
            print(f"   ⏸️ [조건 미달] {coin}: 캔들이 양봉으로 마감하지 않았습니다.")
            return False

        return rejection_reason is None

    # Trade execution / state update
    async def _emit_signal(
        self, target_entity: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str
    ) -> None:
        self._record_signal(target_entity, signal_type, current_price, event_reason)

        if self.dry_run:
            await self._apply_dry_run_result(target_entity, signal_type, current_price, event_reason)
            return

        await self._execute_trade_from_signal(target_entity, signal_type, current_price, event_reason)

    def _record_signal(
        self, target: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str
    ) -> None:
        self.signal_history.append(
            {
                "target_coin": target.target_coin,
                "signal_type": signal_type.value if hasattr(signal_type, "value") else signal_type,
                "price": current_price,
                "event_reason": event_reason,
                "target_status": target.status.value if hasattr(target.status, "value") else target.status,
                "event_time": self.current_event_time,
                "buy_allocation_pct": getattr(target, "buy_allocation_pct", None),
                "wallet_user_id": self.wallet_user_id,
            }
        )

    async def _apply_dry_run_result(
        self, target: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str
    ) -> None:
        try:
            volume = self._simulate_trade_volume(target, signal_type, current_price)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Backtest Trade Simulation Error]")
            self.signal_history[-1]["execution_error"] = str(exc)
            print(
                f"   ❌ [Backtest]: {target.target_coin} / {signal_type} / "
                f"{event_reason} 백테스트 체결 실패 ({type(exc).__name__}: {exc})"
            )
            return

        simulated_status = TargetStatus.HOLDING if signal_type == SignalType.BUY else TargetStatus.EXPIRED
        await self._apply_post_trade_state(target, simulated_status)
        self.signal_history[-1]["result_status"] = simulated_status.value
        self.signal_history[-1]["executed_volume"] = volume
        if self.simulated_wallet is not None:
            self.signal_history[-1]["simulated_balance"] = self.simulated_wallet.balance
        print(
            f"   🧪 [Backtest]: 직접 체결 반영 -> {target.target_coin} / {signal_type} / "
            f"{event_reason} / {current_price:,.0f}원 / 수량: {volume:.8f} / 상태: {simulated_status}"
        )

    def _simulate_trade_volume(self, target: TargetEntity, signal_type: SignalType, current_price: float) -> float:
        if self.simulated_wallet is None:
            raise ValueError("백테스트용 지갑이 없습니다.")

        volume = resolve_trade_volume_from_wallet(
            self.simulated_wallet,
            target.target_coin,
            signal_type,
            current_price,
            buy_allocation_pct=target.buy_allocation_pct if signal_type == SignalType.BUY else None,
        )
        apply_trade_to_wallet_entity(
            self.simulated_wallet,
            target.target_coin,
            signal_type,
            current_price,
            volume,
        )
        return volume

    async def _execute_trade_from_signal(
        self,
        target: TargetEntity,
        signal_type: SignalType,
        current_price: float,
        event_reason: str,
    ) -> None:
        try:
            _, volume = await execute_trade_for_daemon(
                self.wallet_user_id,
                target.target_coin,
                signal_type,
                current_price,
                buy_allocation_pct=target.buy_allocation_pct if signal_type == SignalType.BUY else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Trade Execution Error]")
            self.signal_history[-1]["execution_error"] = str(exc)
            print(
                f"   ❌ [Direct Execution]: {target.target_coin} / {signal_type} / "
                f"{event_reason} 체결 실패 ({type(exc).__name__}: {exc})"
            )
            return

        new_status = TargetStatus.HOLDING if signal_type == SignalType.BUY else TargetStatus.EXPIRED

        self.current_trigger_info = {
            "target_coin": target.target_coin,
            "signal_type": signal_type.value if hasattr(signal_type, "value") else signal_type,
            "price": current_price,
            "event_reason": event_reason,
        }

        await self._apply_post_trade_state(target, new_status)
        self.signal_history[-1]["result_status"] = new_status.value
        self.signal_history[-1]["executed_volume"] = volume
        print(
            f"   ✅ [Direct Execution]: {target.target_coin} {signal_type.value} 체결 완료 "
            f"(수량: {volume:.8f}) -> 상태: {new_status.value}"
        )

    async def _apply_post_trade_state(self, target: TargetEntity, new_status: TargetStatus) -> None:
        target.status = new_status
        await self._update_target_status(target.target_coin, new_status)

        if new_status == TargetStatus.EXPIRED:
            self.active_targets.pop(target.target_coin, None)
            self.current_candles.pop(target.target_coin, None)
            coin_removed = target.target_coin in self.watching_coins
            self.watching_coins.discard(target.target_coin)
            if coin_removed and self.ws_connection:
                try:
                    await self.ws_connection.close()
                except Exception as e:
                    logger.warning("[WebSocket 종료 에러]: %s", e)
                    print(f"   ❌ [WebSocket 종료 에러]: {e}")
            self._schedule_expired_target_refresh()

    # Expired target refresh
    async def _maybe_schedule_expired_target_refresh(self) -> None:
        if self.dry_run or not self.enable_graph or self.refresh_graph is None:
            return

        if self.refresh_task and not self.refresh_task.done():
            return

        expired_targets = await fetch_targets_by_status(self.user_id, [TargetStatus.EXPIRED])
        if not expired_targets:
            return

        self._schedule_expired_target_refresh(expired_targets)

    def _schedule_expired_target_refresh(self, expired_targets: list[TargetEntity] | None = None) -> None:
        if self.dry_run or not self.enable_graph or self.refresh_graph is None:
            return

        if self.refresh_task and not self.refresh_task.done():
            return

        expired_target_coins = [target.target_coin for target in expired_targets] if expired_targets else []
        if expired_target_coins:
            print(f"   ♻️ [Expired Targets]: 타점 재계산 대기 -> {expired_target_coins}")

        self.refresh_task = asyncio.create_task(self._refresh_expired_targets())
        self.refresh_task.add_done_callback(self._on_refresh_task_done)

    async def _refresh_expired_targets(self) -> None:
        expired_targets = await fetch_targets_by_status(self.user_id, [TargetStatus.EXPIRED])
        if not expired_targets:
            return

        expired_coins = [t.target_coin for t in expired_targets]
        print(f"   ♻️ [Target Refresh]: {len(expired_coins)}개 EXPIRED 타점 재계산 시작 -> {expired_coins}")

        await invoke_graph_for_target_refresh(
            self.refresh_graph,
            self.user_id,
            backtest_time=self.current_event_time if self.backtest_mode else None,
            trigger_info=self.current_trigger_info,
        )
        self.current_trigger_info = None
        await self.load_targets_from_db_once()

    def _on_refresh_task_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ [Daemon->Refresh]: 타점 재계산 실패 ({type(exc).__name__}: {exc})")

    async def _update_target_status(self, target_coin: str, new_status: TargetStatus):
        if self.dry_run:
            print(f"   🧪 [Backtest]: DB 상태 업데이트 생략 -> {target_coin}: {new_status}")
            return

        await update_target_status(self.user_id, target_coin, new_status)


async def main(user_id: str) -> None:
    bat = BatDaemon(user_id)

    print("=" * 60)
    print("🦇 Project Magpie: Bat 데몬 시작")
    print("=" * 60)

    await bat.run()


if __name__ == "__main__":
    user_id = "8942621091"
    asyncio.run(main(user_id))
