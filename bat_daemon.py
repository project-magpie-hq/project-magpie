import asyncio
import datetime
import json
import logging
from enum import StrEnum
from typing import Any

import websockets
from pydantic import BaseModel

from agents.meerkat_scanner.schema import TargetSchema, TriggerBasis
from db.mongo import monitoring_target_collection as collection
from main.graph import build_graph

logger = logging.getLogger(__name__)

# DB 조회 및 WebSocket 설정 상수
DB_SYNC_INTERVAL_SECONDS = 60
WS_URI = "wss://api.upbit.com/websocket/v1"
WS_TICKET_NAME = "magpie_bat_daemon"
WS_CANDLE_TYPE = "candle.60m"
DB_TARGET_LIST_LIMIT = 100


class TargetStatus(StrEnum):
    WAITING_BUY = "WAITING_BUY"
    HOLDING = "HOLDING"
    DONE = "DONE"
    EXPIRED = "EXPIRED"


class BatTargetSchema(BaseModel):
    """DB에서 읽어온 감시 타점 데이터"""

    target_schema: TargetSchema
    status: TargetStatus
    created_at: datetime.datetime


class BatDaemon:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.active_targets: dict[str, BatTargetSchema] = {}
        self.watching_coins: set[str] = set()
        self.ws_connection: Any = None
        self.current_candles: dict[str, dict[str, Any]] = {}
        self.magpie_graph = build_graph()
        self.graph_tasks: set[asyncio.Task] = set()

    async def sync_targets_from_db(self) -> None:
        print("🦇 [Bat Daemon]: 감시 레이더 시작! MongoDB와 동기화를 시작합니다.")
        while True:
            try:
                cursor = collection.find({"user_id": {"$in": [self.user_id]}})
                targets = await cursor.to_list(length=DB_TARGET_LIST_LIMIT)

                new_watching_coins: set[str] = set()
                for target in targets:
                    bat_target_schema = BatTargetSchema(
                        target_schema=TargetSchema.model_validate(target),
                        status=target.get("status", TargetStatus.WAITING_BUY),
                        created_at=target.get("created_at", datetime.datetime.now(datetime.UTC)),
                    )
                    new_watching_coins.add(bat_target_schema.target_schema.target_coin)

                    self.active_targets[bat_target_schema.target_schema.target_coin] = bat_target_schema

                if new_watching_coins != self.watching_coins:
                    print(
                        f"   🔄 [DB 동기화]: 감시 대상 코인 변경 감지 -> 기존: {self.watching_coins} / 변경: {new_watching_coins}"
                    )
                    self.watching_coins = new_watching_coins

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

    async def listen_upbit_ws(self) -> None:
        """업비트 웹소켓에 연결하여 1시간 캔들 데이터를 실시간으로 수신하고 타점을 검사합니다."""
        while True:
            if not self.watching_coins:
                await asyncio.sleep(DB_SYNC_INTERVAL_SECONDS)
                continue

            try:
                async with websockets.connect(WS_URI, ping_interval=60, ping_timeout=30) as websocket:
                    self.ws_connection = websocket

                    subscribe_fmt = [
                        {"ticket": WS_TICKET_NAME},
                        {"type": WS_CANDLE_TYPE, "codes": list(self.watching_coins)},
                    ]
                    await websocket.send(json.dumps(subscribe_fmt))
                    print(f"\n📡 [WebSocket]: {list(self.watching_coins)} 1시간 캔들 스트림 수신 시작...\n")

                    while True:
                        data = await websocket.recv()
                        tick: dict[str, Any] = json.loads(data)

                        coin: str | None = tick.get("code")
                        if coin:
                            await self._process_candle_tick(coin, tick)

            except websockets.exceptions.ConnectionClosed as e:
                print(
                    f"   ⚠️ [WebSocket]: 연결 종료(사유: {e}). 코인 목록 변경이거나 네트워크 이슈입니다. 재연결을 시도합니다..."
                )
            except Exception as e:
                logger.exception("[WebSocket 에러]")
                print(f"   ❌ [WebSocket 에러]: {e}")
                await asyncio.sleep(2)

    async def _process_candle_tick(self, coin: str, tick: dict[str, Any]) -> None:
        """웹소켓으로 들어오는 실시간 캔들 조각을 받아 처리하는 메인 허브"""
        target = self.active_targets.get(coin)
        if not target:
            return

        current_price: float | None = tick.get("trade_price")
        candle_time_str: str | None = tick.get("candle_date_time_kst")

        if current_price is None:
            return

        # 1. ⚡ [실시간 검사]: 매 틱마다 즉시 발동하는 로직 (익절/손절, TOUCH 매수)
        await self._check_realtime_signals(coin, current_price, target)

        # 2. ⏳ [캔들 마감 검사]: 시간이 바뀌었는지 확인
        last_candle = self.current_candles.get(coin)

        if last_candle and last_candle.get("candle_date_time_kst") != candle_time_str:
            print(
                f"\n⏰ [캔들 마감 감지]: {coin}의 {last_candle['candle_date_time_kst']} 캔들 마감. CLOSE 조건 판독 시작."
            )
            await self._evaluate_closed_candle(coin, last_candle, target)

        # 3. 메모리 갱신: 방금 들어온 최신 캔들 상태로 덮어쓰기
        self.current_candles[coin] = tick

    async def _check_realtime_signals(self, coin: str, current_price: float, target: BatTargetSchema) -> None:
        """실시간(TOUCH) 조건 판별: 손절, 익절, TOUCH 방식의 매수"""
        if target.status == TargetStatus.HOLDING:
            if current_price >= target.target_schema.take_profit_price:
                print(f"💰 [PROFIT SIGNAL] {coin} 익절가 돌파! (현재가: {current_price:,.0f}원)")
                target.status = TargetStatus.DONE
                await collection.update_one({"target_coin": coin}, {"$set": {"status": TargetStatus.DONE}})
                self._schedule_graph_run(target, "SELL", current_price, "take_profit_hit")
            elif current_price <= target.target_schema.stop_loss_price:
                print(f"🩸 [STOP LOSS SIGNAL] {coin} 손절선 붕괴! 비상 탈출! (현재가: {current_price:,.0f}원)")
                target.status = TargetStatus.DONE
                await collection.update_one({"target_coin": coin}, {"$set": {"status": TargetStatus.DONE}})
                self._schedule_graph_run(target, "SELL", current_price, "stop_loss_hit")

        elif (
            target.status == TargetStatus.WAITING_BUY
            and target.target_schema.trigger_basis == TriggerBasis.TOUCH
            and target.target_schema.buy_price_lower_limit
            <= current_price
            <= target.target_schema.buy_price_upper_limit
        ):
            print(f"🚀 [BUY SIGNAL - TOUCH] {coin} 매수 영역 진입! (현재가: {current_price:,.0f}원)")
            target.status = TargetStatus.HOLDING
            await collection.update_one({"target_coin": coin}, {"$set": {"status": TargetStatus.HOLDING}})
            self._schedule_graph_run(target, "BUY", current_price, "touch_entry_hit")

    async def _evaluate_closed_candle(self, coin: str, closed_candle: dict[str, Any], target: BatTargetSchema):
        """방금 마감된 온전한 1시간 캔들을 기반으로 유효성 및 CLOSE 조건을 판별"""
        if target.status != TargetStatus.WAITING_BUY:
            return

        now = datetime.datetime.now(datetime.UTC)
        hours_passed = (now - target.created_at.replace(tzinfo=datetime.UTC)).total_seconds() / 3600
        if hours_passed >= target.target_schema.valid_for_n_candles:
            print(
                f"   ⏳ [만료] {coin}: 설정된 타점 유효기간({target.target_schema.valid_for_n_candles}시간) 경과로 폐기."
            )
            await self._update_target_status(target, "EXPIRED")
            target.status = TargetStatus.EXPIRED
            return

        if target.target_schema.trigger_basis != TriggerBasis.CLOSE:
            return

        close_price: float | None = closed_candle.get("trade_price")
        open_price: float | None = closed_candle.get("opening_price")
        volume: float | None = closed_candle.get("candle_acc_trade_volume")
        if close_price is None or open_price is None or volume is None:
            logger.warning("[%s] 마감 캔들 데이터 누락 (close/open/volume)", coin)
            return

        is_bullish = close_price > open_price

        if not (
            target.target_schema.buy_price_lower_limit <= close_price <= target.target_schema.buy_price_upper_limit
        ):
            return

        if volume < target.target_schema.min_volume_threshold:
            print(f"   ⏸️ [조건 미달] {coin}: 1시간 거래량({volume:,.0f})이 최소 기준에 미달합니다.")
            return

        if target.target_schema.requires_bullish_close and not is_bullish:
            print(f"   ⏸️ [조건 미달] {coin}: 캔들이 양봉으로 마감하지 않았습니다.")
            return

        print(f"🚀 [BUY SIGNAL - CLOSE] {coin} 1시간 캔들 마감 조건 완벽 충족! (종가: {close_price:,.0f}원)")
        target.status = TargetStatus.HOLDING
        await self._update_target_status(target, "HOLDING")
        self._schedule_graph_run(target, "BUY", close_price, "close_entry_hit")

    async def _update_target_status(self, target: BatTargetSchema, new_status: str):
        await collection.update_one(
            {"user_id": self.user_id, "target_coin": target.target_schema.target_coin},
            {"$set": {"status": new_status}},
        )

    def _schedule_graph_run(
        self,
        target: BatTargetSchema,
        signal_type: str,
        current_price: float,
        event_reason: str,
    ):
        task = asyncio.create_task(self._invoke_graph_for_trigger(target, signal_type, current_price, event_reason))
        self.graph_tasks.add(task)
        task.add_done_callback(self._on_graph_task_done)

    def _on_graph_task_done(self, task: asyncio.Task):
        self.graph_tasks.discard(task)
        try:
            task.result()
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ [Daemon->Graph]: 그래프 실행 실패 ({type(exc).__name__}: {exc})")

    def _build_trigger_event(
        self,
        target: BatTargetSchema,
        signal_type: str,
        current_price: float,
        event_reason: str,
    ) -> dict[str, Any]:
        monitoring_target = {
            "user_id": self.user_id,
            "target_coin": target.target_schema.target_coin,
            "buy_price_upper_limit": target.target_schema.buy_price_upper_limit,
            "buy_price_lower_limit": target.target_schema.buy_price_lower_limit,
            "take_profit_price": target.target_schema.take_profit_price,
            "stop_loss_price": target.target_schema.stop_loss_price,
            "trigger_basis": target.target_schema.trigger_basis,
            "requires_bullish_close": target.target_schema.requires_bullish_close,
            "min_volume_threshold": target.target_schema.min_volume_threshold,
            "valid_for_n_candles": target.target_schema.valid_for_n_candles,
            "status": target.status,
            "created_at": target.created_at,
        }

        return {
            **monitoring_target,
            "market": target.target_schema.target_coin,
            "signal_type": signal_type,
            "current_price": current_price,
            "event_reason": event_reason,
            "event_source": "bat_daemon",
            "triggered_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "monitoring_target": monitoring_target,
        }

    def _build_system_event_message(self, trigger_event: dict[str, Any]) -> str:
        return (
            "[SYSTEM_EVENT: TRIGGER_MONITORING_UPDATE]\n"
            f"Bat daemon detected a {trigger_event['signal_type']} signal on {trigger_event['target_coin']} "
            f"at approximately {trigger_event['current_price']:,.0f} KRW.\n"
            "Beaver 제안서를 우선 실행안으로 검토하고, Owl은 유지/축소/보류 여부를 명확히 판단한 뒤 "
            "Meerkat에게 금액 중심 피드백을 전달하세요."
        )

    async def _invoke_graph_for_trigger(
        self,
        target: BatTargetSchema,
        signal_type: str,
        current_price: float,
        event_reason: str,
    ):
        trigger_event = self._build_trigger_event(target, signal_type, current_price, event_reason)
        thread_id = (
            f"daemon:{self.user_id}:{target.target_schema.target_coin}:{signal_type}:"
            f"{datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%S')}"
        )
        inputs = {
            "user_id": self.user_id,
            "messages": [("user", self._build_system_event_message(trigger_event))],
            "trigger_event": trigger_event,
        }

        print(
            f"   🤝 [Daemon->Graph]: {self.user_id} / {target.target_schema.target_coin} / "
            f"{signal_type} 이벤트를 Beaver->Owl 그래프로 전달합니다."
        )
        result = await self.magpie_graph.ainvoke(inputs, config={"configurable": {"thread_id": thread_id}})

        beaver_plan = result.get("beaver_plan") or {}
        owl_decision = result.get("owl_decision") or {}
        if beaver_plan:
            print(
                f"   🦫 [Daemon->Graph]: Beaver summary={beaver_plan.get('summary_action')} "
                f"/ actions={len(beaver_plan.get('actions') or [])}"
            )
            print("   🦫 [Daemon->Graph][beaver_plan]")
            print(json.dumps(beaver_plan, ensure_ascii=False, indent=2, default=str))
        if owl_decision:
            print(
                f"   🦉 [Daemon->Graph]: Owl status={owl_decision.get('status')} / next={owl_decision.get('next_step')}"
            )
            print("   🦉 [Daemon->Graph][owl_decision]")
            print(json.dumps(owl_decision, ensure_ascii=False, indent=2, default=str))


async def main(user_id: str) -> None:
    bat = BatDaemon(user_id)

    print("=" * 60)
    print("🦇 Project Magpie: Bat 데몬 시작")
    print("=" * 60)

    await asyncio.gather(bat.sync_targets_from_db(), bat.listen_upbit_ws())


if __name__ == "__main__":
    user_id = "test_developer_001"
    asyncio.run(main(user_id))
