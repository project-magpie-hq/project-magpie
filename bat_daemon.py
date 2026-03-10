import asyncio
import json

import websockets

from db.mongo import monitoring_target_collection as collection


class BatDaemon:
    def __init__(self):
        self.active_targets = {}
        self.watching_coins = set()
        self.ws_connection = None

    async def sync_targets_from_db(self):
        print("🦇 [Bat Daemon]: 감시 레이더 가동! MongoDB와 동기화를 시작합니다.")
        while True:
            try:
                cursor = collection.find({"status": {"$ne": "DONE"}})
                targets = await cursor.to_list(length=100)

                new_watching_coins = set()
                for t in targets:
                    coin = t["target_coin"]
                    new_watching_coins.add(coin)

                    db_status = t.get("status", "WAITING_BUY")
                    self.active_targets[coin] = {
                        "buy_price": t["target_buy_price"],
                        "profit_price": t["take_profit_price"],
                        "loss_price": t["stop_loss_price"],
                        "state": db_status,
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

            await asyncio.sleep(10)

    async def listen_upbit_ws(self):
        """업비트 웹소켓에 연결하여 틱 데이터를 실시간으로 수신하고 타점을 검사합니다."""
        uri = "wss://api.upbit.com/websocket/v1"

        while True:
            if not self.watching_coins:
                await asyncio.sleep(2)
                continue

            try:
                async with websockets.connect(uri, ping_interval=60, ping_timeout=30) as websocket:
                    self.ws_connection = websocket

                    subscribe_fmt = [
                        {"ticket": "magpie_bat_daemon"},
                        {"type": "ticker", "codes": list(self.watching_coins)},
                    ]
                    await websocket.send(json.dumps(subscribe_fmt))
                    print(f"\n📡 [WebSocket]: {list(self.watching_coins)} 실시간 틱 수신 시작...\n")

                    while True:
                        data = await websocket.recv()
                        # 업비트는 bytes 형태로 데이터를 보내주므로 json.loads가 알아서 파싱합니다.
                        tick = json.loads(data)

                        coin = tick.get("code")
                        current_price = tick.get("trade_price")

                        if coin and current_price:
                            await self._check_signals(coin, current_price)

            except websockets.exceptions.ConnectionClosed as e:
                # DB 동기화에서 close()를 호출했거나, 업비트 측에서 끊은 경우 자연스럽게 여기로 넘어옴
                print(
                    f"   ⚠️ [WebSocket]: 연결 종료(사유: {e}). 코인 목록 변경이거나 네트워크 이슈입니다. 재연결을 시도합니다..."
                )
            except Exception as e:
                print(f"   ❌ [WebSocket 에러]: {e}")

    async def _check_signals(self, coin: str, current_price: float):
        print(f"   ✅ [수신] {coin}: {current_price:,.0f} 원")
        # target = self.active_targets.get(coin)
        # if not target:
        #     return

        # state = target["state"]

        # if state == "WAITING_BUY":
        #     if current_price <= target["buy_price"]:
        #         print(f"🚀 [BUY SIGNAL] {coin} 매수가 도달! (현재가: {current_price:,.0f}원)")

        #         # 1. 메모리 상태 변경
        #         target["state"] = "HOLDING"
        #         # 2. 🚨 DB 상태 즉시 업데이트 (데몬이 죽어도 기억하도록)
        #         await collection.update_one({"target_coin": coin}, {"$set": {"status": "HOLDING"}})

        # elif state == "HOLDING":
        #     if current_price >= target["profit_price"]:
        #         print(f"💰 [PROFIT SIGNAL] {coin} 익절가 도달!")
        #         target["state"] = "DONE"
        #         await collection.update_one({"target_coin": coin}, {"$set": {"status": "DONE"}})

        #     elif current_price <= target["loss_price"]:
        #         print(f"🩸 [STOP LOSS SIGNAL] {coin} 손절가 도달!")
        #         target["state"] = "DONE"
        #         await collection.update_one({"target_coin": coin}, {"$set": {"status": "DONE"}})


async def main():
    bat = BatDaemon()

    print("=" * 60)
    print("🦇 Project Magpie: Bat 데몬 시작")
    print("=" * 60)

    await asyncio.gather(bat.sync_targets_from_db(), bat.listen_upbit_ws())


if __name__ == "__main__":
    asyncio.run(main())
