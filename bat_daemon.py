import asyncio
import datetime
import json

import websockets

from db.mongo import monitoring_target_collection as collection


class BatDaemon:
    def __init__(self):
        self.active_targets = {}
        self.watching_coins = set()
        self.ws_connection = None
        self.current_candles = {}

    async def sync_targets_from_db(self):
        print("🦇 [Bat Daemon]: 감시 레이더 시작! MongoDB와 동기화를 시작합니다.")
        while True:
            try:
                cursor = collection.find({"status": {"$in": ["WAITING_BUY", "HOLDING"]}})
                targets = await cursor.to_list(length=100)

                new_watching_coins = set()
                for t in targets:
                    coin = t["target_coin"]
                    new_watching_coins.add(coin)

                    self.active_targets[coin] = {
                        "buy_upper": t.get("buy_price_upper_limit", 0),
                        "buy_lower": t.get("buy_price_lower_limit", 0),
                        "profit_price": t.get("take_profit_price", 0),
                        "loss_price": t.get("stop_loss_price", 0),
                        "trigger_basis": t.get("trigger_basis", "TOUCH"),
                        "requires_bullish": t.get("requires_bullish_close", False),
                        "min_volume": t.get("min_volume_threshold", 0),
                        "valid_for_n_candles": t.get("valid_for_n_candles", 24),
                        "state": t.get("status", "WAITING_BUY"),
                        "created_at": t.get("created_at", datetime.now()),
                    }

                if new_watching_coins != self.watching_coins:
                    print(
                        f"   🔄 [DB 동기화]: 감시 대상 코인 변경 감지 -> 기존: {self.watching_coins} / 변경: {new_watching_coins}"
                    )
                    self.watching_coins = new_watching_coins

                    if self.ws_connection:
                        try:
                            await self.ws_connection.close()
                        except Exception as e:
                            print(f"   ❌ [WebSocket 종료 에러]: {e}")

            except Exception as e:
                print(f"   ❌ [DB 에러]: {e}")

            await asyncio.sleep(60)

    async def listen_upbit_ws(self):
        """업비트 웹소켓에 연결하여 1시간 캔들 데이터를 실시간으로 수신하고 타점을 검사합니다."""
        uri = "wss://api.upbit.com/websocket/v1"

        while True:
            if not self.watching_coins:
                await asyncio.sleep(60)
                continue

            try:
                async with websockets.connect(uri, ping_interval=60, ping_timeout=30) as websocket:
                    self.ws_connection = websocket

                    subscribe_fmt = [
                        {"ticket": "magpie_bat_daemon"},
                        {"type": "candle.60m", "codes": list(self.watching_coins)},
                    ]
                    await websocket.send(json.dumps(subscribe_fmt))
                    print(f"\n📡 [WebSocket]: {list(self.watching_coins)} 1시간 캔들 스트림 수신 시작...\n")

                    while True:
                        data = await websocket.recv()
                        tick = json.loads(data)

                        coin = tick.get("code")

                        if coin:
                            await self._process_candle_tick(coin, tick)

            except websockets.exceptions.ConnectionClosed as e:
                print(
                    f"   ⚠️ [WebSocket]: 연결 종료(사유: {e}). 코인 목록 변경이거나 네트워크 이슈입니다. 재연결을 시도합니다..."
                )
            except Exception as e:
                print(f"   ❌ [WebSocket 에러]: {e}")
                await asyncio.sleep(2)

    async def _process_candle_tick(self, coin: str, tick: dict):
        """웹소켓으로 들어오는 실시간 캔들 조각을 받아 처리하는 메인 허브"""
        target = self.active_targets.get(coin)
        if not target:
            return

        current_price = tick.get("trade_price")
        candle_time_str = tick.get("candle_date_time_kst")

        # 1. ⚡ [실시간 검사]: 매 틱마다 즉시 발동하는 로직 (익절/손절, TOUCH 매수)
        await self._check_realtime_signals(coin, current_price, target)

        # 2. ⏳ [캔들 마감 검사]: 시간이 바뀌었는지 확인
        last_candle = self.current_candles.get(coin)

        if last_candle and last_candle["candle_date_time_kst"] != candle_time_str:
            print(
                f"\n⏰ [캔들 마감 감지]: {coin}의 {last_candle['candle_date_time_kst']} 캔들 마감. CLOSE 조건 판독 시작."
            )
            await self._evaluate_closed_candle(coin, last_candle, target)

        # 3. 메모리 갱신: 방금 들어온 최신 캔들 상태로 덮어쓰기
        self.current_candles[coin] = tick

    async def _check_realtime_signals(self, coin: str, current_price: float, target: dict):
        """실시간(TOUCH) 조건 판별: 손절, 익절, TOUCH 방식의 매수"""
        state = target["state"]

        if state == "HOLDING":
            if current_price >= target["profit_price"]:
                print(f"💰 [PROFIT SIGNAL] {coin} 익절가 돌파! (현재가: {current_price:,.0f}원)")
                target["state"] = "DONE"
                await collection.update_one({"target_coin": coin}, {"$set": {"status": "DONE"}})
            elif current_price <= target["loss_price"]:
                print(f"🩸 [STOP LOSS SIGNAL] {coin} 손절선 붕괴! 비상 탈출! (현재가: {current_price:,.0f}원)")
                target["state"] = "DONE"
                await collection.update_one({"target_coin": coin}, {"$set": {"status": "DONE"}})

        elif (
            state == "WAITING_BUY"
            and target["trigger_basis"] == "TOUCH"
            and target["buy_lower"] <= current_price <= target["buy_upper"]
        ):
            print(f"🚀 [BUY SIGNAL - TOUCH] {coin} 매수 영역 진입! (현재가: {current_price:,.0f}원)")
            target["state"] = "HOLDING"
            await collection.update_one({"target_coin": coin}, {"$set": {"status": "HOLDING"}})

    async def _evaluate_closed_candle(self, coin: str, closed_candle: dict, target: dict):
        """방금 마감된 온전한 1시간 캔들을 기반으로 유효성 및 CLOSE 조건을 판별"""
        if target["state"] != "WAITING_BUY":
            return

        now = datetime.now()

        # 1. 캔들 유효기간 만료 검사 (EXPIRED)
        hours_passed = (now - target["created_at"]).total_seconds() / 3600
        if hours_passed >= target["valid_for_n_candles"]:
            print(f"   ⏳ [만료] {coin}: 설정된 타점 유효기간({target['valid_for_n_candles']}시간) 경과로 폐기.")
            await collection.update_one({"target_coin": coin}, {"$set": {"status": "EXPIRED"}})
            target["state"] = "EXPIRED"
            return

        # 2. CLOSE 방식 매수 조건 검사
        if target["trigger_basis"] == "CLOSE":
            close_price = closed_candle.get("trade_price")
            open_price = closed_candle.get("opening_price")
            volume = closed_candle.get("candle_acc_trade_volume")
            is_bullish = close_price > open_price

            # [조건 검사] 매수 영역 -> 거래량 -> 양봉 마감
            if target["buy_lower"] <= close_price <= target["buy_upper"]:
                if volume >= target["min_volume"]:
                    if not target["requires_bullish"] or (target["requires_bullish"] and is_bullish):
                        print(
                            f"🚀 [BUY SIGNAL - CLOSE] {coin} 1시간 캔들 마감 조건 완벽 충족! (종가: {close_price:,.0f}원)"
                        )
                        target["state"] = "HOLDING"
                        await collection.update_one({"target_coin": coin}, {"$set": {"status": "HOLDING"}})
                    else:
                        print(f"   ⏸️ [조건 미달] {coin}: 캔들이 양봉으로 마감하지 않았습니다.")
                else:
                    print(f"   ⏸️ [조건 미달] {coin}: 1시간 거래량({volume:,.0f})이 최소 기준에 미달합니다.")


async def main():
    bat = BatDaemon()

    print("=" * 60)
    print("🦇 Project Magpie: Bat 데몬 시작")
    print("=" * 60)

    await asyncio.gather(bat.sync_targets_from_db(), bat.listen_upbit_ws())


if __name__ == "__main__":
    asyncio.run(main())
