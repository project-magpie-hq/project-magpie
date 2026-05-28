import asyncio
import logging
from typing import Any

from websockets.exceptions import ConnectionClosed

from bat_daemon.constant import DB_SYNC_INTERVAL_SECONDS, SignalType
from bat_daemon.integrations.graph_event import invoke_graph_for_trigger
from bat_daemon.market_data.candle import CandleTick, ClosedCandle, is_new_candle, parse_closed_candle, parse_tick
from bat_daemon.market_data.upbit_ws import connect_upbit_ws, receive_candle_tick, subscribe_candles
from bat_daemon.signals.rules import close_buy_rejection_reason, is_touch_buy_signal, should_check_close_buy
from bat_daemon.stores.target_store import fetch_target_map, update_target_status
from db.entity import TargetEntity
from magpie_agent.agents.meerkat_scanner.schema import TargetStatus
from magpie_agent.graphs.signal_trigger import build_signal_trigger_graph

logger = logging.getLogger(__name__)


class BatDaemon:
    def __init__(self, user_id: str, *, dry_run: bool = False, enable_graph: bool = True) -> None:
        self.user_id = user_id
        self.dry_run = dry_run
        self.enable_graph = enable_graph
        self.active_targets: dict[str, TargetEntity] = {}
        self.watching_coins: set[str] = set()
        self.ws_connection: Any = None
        self.current_candles: dict[str, dict[str, Any]] = {}
        self.magpie_graph = build_signal_trigger_graph() if enable_graph and not dry_run else None
        self.graph_tasks: set[asyncio.Task] = set()
        self.signal_history: list[dict[str, Any]] = []
        self.current_event_time: str | None = None

    async def run(self) -> None:
        await asyncio.gather(self.sync_targets_from_db(), self.listen_upbit_ws())

    async def load_targets_from_db_once(self) -> None:
        """MongoDB에 저장된 현재 모니터링 타겟을 한 번 로드합니다."""
        self.active_targets = await fetch_target_map(self.user_id)
        self.watching_coins = set(self.active_targets)

    async def sync_targets_from_db(self) -> None:
        print("🦇 [Bat Daemon]: 감시 레이더 시작! MongoDB와 동기화를 시작합니다.")
        while True:
            try:
                await self._sync_targets_once()
            except Exception as e:
                logger.exception("[DB 동기화 에러]")
                print(f"   ❌ [DB 에러]: {e}")

            await asyncio.sleep(DB_SYNC_INTERVAL_SECONDS)

    async def listen_upbit_ws(self) -> None:
        """업비트 웹소켓에 연결하여 1시간 캔들 데이터를 실시간으로 수신하고 타점을 검사합니다."""
        while True:
            if not self.watching_coins:
                await asyncio.sleep(DB_SYNC_INTERVAL_SECONDS)
                continue

            try:
                await self._stream_upbit_candles()
            except ConnectionClosed as e:
                print(
                    f"   ⚠️ [WebSocket]: 연결 종료(사유: {e}). 코인 목록 변경이거나 네트워크 이슈입니다. 재연결을 시도합니다..."
                )
            except Exception as e:
                logger.exception("[WebSocket 에러]")
                print(f"   ❌ [WebSocket 에러]: {e}")
                await asyncio.sleep(2)

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
        if is_new_candle(last_candle, parsed_tick.candle_time):
            await self._evaluate_closed_candle_with_log(coin, last_candle, target)

        self.current_candles[coin] = tick

    async def flush_current_candles(self) -> None:
        """현재 메모리에 남아 있는 마지막 캔들을 마감 캔들로 평가합니다."""
        for coin, last_candle in list(self.current_candles.items()):
            target = self.active_targets.get(coin)
            if target:
                await self._evaluate_closed_candle(coin, last_candle, target)

    async def _sync_targets_once(self) -> None:
        old_watching_coins = set(self.watching_coins)
        await self.load_targets_from_db_once()

        if self.watching_coins == old_watching_coins:
            return

        print(
            f"   🔄 [DB 동기화]: 감시 대상 코인 변경 감지 -> 기존: {old_watching_coins} / 변경: {self.watching_coins}"
        )
        await self._close_ws_connection()

    async def _close_ws_connection(self) -> None:
        if not self.ws_connection:
            return

        try:
            await self.ws_connection.close()
        except Exception as e:
            logger.warning("[WebSocket 종료 에러]: %s", e)
            print(f"   ❌ [WebSocket 종료 에러]: {e}")

    async def _stream_upbit_candles(self) -> None:
        async with connect_upbit_ws() as websocket:
            self.ws_connection = websocket

            await subscribe_candles(websocket, self.user_id, self.watching_coins)
            print(f"\n📡 [WebSocket]: {list(self.watching_coins)} 1시간 캔들 스트림 수신 시작...\n")

            while True:
                await self._receive_ws_tick(websocket)

    async def _receive_ws_tick(self, websocket: Any) -> None:
        coin, tick = await receive_candle_tick(websocket)
        if coin:
            await self.process_candle_tick(coin, tick)

    async def _evaluate_closed_candle_with_log(
        self, coin: str, closed_candle: dict[str, Any] | None, target: TargetEntity
    ) -> None:
        if not closed_candle:
            return

        print(
            f"\n⏰ [캔들 마감 감지]: {coin}의 {closed_candle['candle_date_time_kst']} 캔들 마감. CLOSE 조건 판독 시작."
        )
        await self._evaluate_closed_candle(coin, closed_candle, target)

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

    async def _emit_signal(
        self, target_entity: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str
    ) -> None:
        target_entity.status = TargetStatus.CHECKING
        await self._update_target_status(target_entity.target_coin, TargetStatus.CHECKING)
        self._dispatch_signal(target_entity, signal_type, current_price, event_reason)

    def _dispatch_signal(self, target: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str):
        self._record_signal(target, signal_type, current_price, event_reason)

        if self.dry_run or not self.enable_graph:
            self._apply_dry_run_result(target, signal_type, current_price, event_reason)
            return

        self._schedule_graph_task(target, signal_type, current_price, event_reason)

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
            }
        )

    def _apply_dry_run_result(
        self, target: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str
    ) -> None:
        simulated_status = TargetStatus.HOLDING if signal_type == SignalType.BUY else TargetStatus.DONE
        target.status = simulated_status
        self.signal_history[-1]["result_status"] = simulated_status.value
        print(
            f"   🧪 [Backtest]: Graph 호출 생략 -> {target.target_coin} / {signal_type} / "
            f"{event_reason} / {current_price:,.0f}원 / 상태: {simulated_status}"
        )

    def _schedule_graph_task(
        self, target: TargetEntity, signal_type: SignalType, current_price: float, event_reason: str
    ) -> None:
        task = asyncio.create_task(
            invoke_graph_for_trigger(
                self.magpie_graph,
                self.user_id,
                target,
                signal_type,
                current_price,
                event_reason,
            )
        )
        self.graph_tasks.add(task)
        task.add_done_callback(self._on_graph_task_done)

    def _on_graph_task_done(self, task: asyncio.Task):
        self.graph_tasks.discard(task)
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ [Daemon->Graph]: 그래프 실행 실패 ({type(exc).__name__}: {exc})")

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
