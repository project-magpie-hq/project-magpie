import asyncio

import pandas as pd
from data_loader import fetch_historical_candles


class TimeMachineSimulator:
    def __init__(self, historical_data_map: dict[str, pd.DataFrame], initial_strategy: dict):
        self.data_map = historical_data_map
        self.timeline = sorted(set().union(*[df.index for df in historical_data_map.values()]))

        # A/B case 상태 초기화
        self.state_A = {
            "name": "A (통제군: 타점만 갱신)",
            "holdings": {},
            "stats": {},
            "strategy": initial_strategy,
            "targets": {},
            "trade_history": [],
        }

        self.state_B = {
            "name": "B (비교군: 전략+타점 동시 갱신)",
            "holdings": {},
            "stats": {},
            "strategy": initial_strategy,
            "targets": {},
            "trade_history": [],
        }

    async def run_simulation(self):
        print("🚀 [Time Machine]: A/B 시뮬레이션을 시작합니다...\n")

        for current_time in self.timeline:
            self._check_virtual_execution(self.state_A, current_time)
            self._check_virtual_execution(self.state_B, current_time)

            if current_time.hour == 0:
                print(f"\n📅 [타점/전략 재계산]: {current_time.strftime('%Y-%m-%d')}")
                await asyncio.gather(self._update_account_A(current_time), self._update_account_B(current_time))

        print("\n🏁 [Time Machine]: 시뮬레이션 종료!")
        self._print_report()

    # ========================================== #
    # ⚙️ 캔들 내부(Intra-candle) 가상 체결 로직
    # ========================================== #
    def _check_virtual_execution(self, account, current_time):
        targets = account.get("targets", {})

        for coin, target in list(targets.items()):
            if target.get("state") in ["DONE", "EXPIRED"]:
                continue

            # 해당 코인의 현재 시간 캔들이 없으면 패스 (코인마다 상장일이 다를 수 있음)
            if current_time not in self.data_map[coin].index:
                continue

            candle = self.data_map[coin].loc[current_time]
            state = target["state"]
            low, high, close, open_p, vol = (
                candle["low"],
                candle["high"],
                candle["close"],
                candle["open"],
                candle["volume"],
            )
            is_bullish = close > open_p

            if coin not in account["stats"]:
                account["stats"][coin] = {"invested": 0, "returned": 0}

            # ⏳ 1. 만료 시간 체크
            target["hours_passed"] = target.get("hours_passed", 0) + 1
            if state == "WAITING_BUY" and target["hours_passed"] > target["valid_for_n_candles"]:
                target["state"] = "EXPIRED"
                account["trade_history"].append(f"[{current_time}] ⏳ {coin} 타점 만료")
                continue

            # 🔴 2. 매도 로직 (손절 최우선 검사)
            if state == "HOLDING" and account["holdings"].get(coin, 0) == 1:
                sell_price = None
                reason = ""

                if low <= target["loss_price"]:
                    sell_price = target["loss_price"]
                    reason = "🩸 손절"
                elif high >= target["profit_price"]:
                    sell_price = target["profit_price"]
                    reason = "💰 익절"

                if sell_price:
                    account["stats"][coin]["returned"] += sell_price
                    account["holdings"][coin] = 0
                    target["state"] = "DONE"
                    account["trade_history"].append(
                        f"[{current_time}] {reason} | {coin} | 1개 매도 체결: {sell_price:,.0f}원"
                    )

            # 🟢 3. 매수 로직
            elif state == "WAITING_BUY":
                buy_price = None

                if target["trigger_basis"] == "TOUCH" and low <= target["buy_upper"]:
                    if low >= target["buy_lower"]:
                        buy_price = target["buy_upper"]  # 슬리피지 고려 가장 불리한 체결가

                elif target["trigger_basis"] == "CLOSE" and target["buy_lower"] <= close <= target["buy_upper"]:
                    if vol >= target["min_volume"] and (not target["requires_bullish"] or is_bullish):
                        buy_price = close

                # 현금 잔고 체크 없이 무조건 1개 진입
                if buy_price:
                    account["stats"][coin]["invested"] += buy_price
                    account["holdings"][coin] = 1
                    target["state"] = "HOLDING"
                    account["trade_history"].append(
                        f"[{current_time}] 🚀 매수 | {coin} | 1개 진입 체결: {buy_price:,.0f}원"
                    )

    # ========================================== #
    # 🧠 에이전트 개입 로직
    # ========================================== #
    async def _update_account_A(self, current_time):
        """A계좌: 고정 전략으로 타점만 미어캣에게 새로 받아옴"""
        # TODO: 실제 LangGraph 에이전트 연동
        self.state_A["targets"] = await self.meerkat_call()

    async def _update_account_B(self, current_time):
        """B계좌: 부엉이가 피드백 보고 전략 수정 -> 미어캣이 새 타점 산출"""
        # TODO: 실제 LangGraph 에이전트 연동
        self.state_B["targets"] = await self.owl_call()

    async def meerkat_call(self):
        """테스트를 위한 미어캣 에이전트 호출"""
        # TODO: 실제 LangGraph 에이전트 연동
        return {
            "KRW-BTC": {
                "buy_upper": 95000000,
                "buy_lower": 90000000,
                "profit_price": 105000000,
                "loss_price": 85000000,
                "trigger_basis": "CLOSE",
                "requires_bullish": True,
                "min_volume": 100,
                "valid_for_n_candles": 24,
                "state": "WAITING_BUY",
                "hours_passed": 0,
            },
            "KRW-ETH": {
                "buy_upper": 4500000,
                "buy_lower": 4000000,
                "profit_price": 5000000,
                "loss_price": 3800000,
                "trigger_basis": "TOUCH",
                "requires_bullish": False,
                "min_volume": 500,
                "valid_for_n_candles": 24,
                "state": "WAITING_BUY",
                "hours_passed": 0,
            },
        }

    async def owl_call(self):
        """테스트를 위한 부엉이 에이전트 호출"""
        # TODO: 실제 LangGraph 에이전트 연동
        return {
            "KRW-BTC": {
                "buy_upper": 95000000,
                "buy_lower": 90000000,
                "profit_price": 105000000,
                "loss_price": 85000000,
                "trigger_basis": "CLOSE",
                "requires_bullish": True,
                "min_volume": 100,
                "valid_for_n_candles": 24,
                "state": "WAITING_BUY",
                "hours_passed": 0,
            },
            "KRW-ETH": {
                "buy_upper": 4500000,
                "buy_lower": 4000000,
                "profit_price": 5000000,
                "loss_price": 3800000,
                "trigger_basis": "TOUCH",
                "requires_bullish": False,
                "min_volume": 500,
                "valid_for_n_candles": 24,
                "state": "WAITING_BUY",
                "hours_passed": 0,
            },
        }

    def _print_report(self):
        print("=" * 50)
        print("📊 [테스트 결과]")
        for account in [self.state_A, self.state_B]:
            print(f"🔹 {account['name']}")

            coin_rois = []

            for coin, stats in account["stats"].items():
                invested = stats["invested"]
                returned = stats["returned"]

                # 투자가 한 번도 일어나지 않은 코인은 패스
                if invested == 0:
                    continue

                # 만약 시뮬레이션 종료 시점까지 HOLDING 상태라면, 마지막 캔들 종가로 평가 금액 합산
                if account["holdings"].get(coin, 0) == 1:
                    last_price = self.data_map[coin].iloc[-1]["close"]
                    returned += last_price

                roi = ((returned - invested) / invested) * 100
                coin_rois.append(roi)

                print(
                    f"   - {coin}: 수익률 {roi:>6.2f}% (총 누적 투입: {invested:,.0f}원 / 총 누적 회수: {returned:,.0f}원)"
                )

            # 전체 평균 수익률 계산
            if coin_rois:
                avg_roi = sum(coin_rois) / len(coin_rois)
                print(f"   ➡️ 📈 전체 포트폴리오 평균 수익률: {avg_roi:+.2f}%\n")
            else:
                print("   ➡️ 📈 체결된 내역이 없습니다.\n")

            print("\n상세 거래 내역:")
            print("\n".join(account["trade_history"]))
        print("=" * 60)


if __name__ == "__main__":
    target_coins = ["KRW-BTC", "KRW-ETH"]
    test_days = 30  # 최근 30일치(약 720시간) 데이터로 백테스트 진행

    print(f"📥 데이터 로딩 시작 (최근 {test_days}일)...")
    mock_data_map = {}

    for coin in target_coins:
        print(f"   - {coin} 1시간 캔들 수집 중...")
        df = fetch_historical_candles(coin, days=test_days)
        if not df.empty:
            mock_data_map[coin] = df
            print(f"     ✅ {len(df)}개의 캔들 로드 완료 (시작: {df.index[0]}, 종료: {df.index[-1]})")
        else:
            print("     ❌ 데이터 로드 실패")

    print("✅ 모든 데이터 로딩 완료!\n")
    print(f"{mock_data_map}")

    initial_strategy = {"type": "기본 스윙"}
    simulator = TimeMachineSimulator(mock_data_map, initial_strategy)
    asyncio.run(simulator.run_simulation())
