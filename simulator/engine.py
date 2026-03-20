import asyncio

import pandas as pd

from main.graph import build_graph
from simulator.constants import TRIGGER_PHRASE


class TimeMachineSimulator:
    def __init__(self, historical_data_map: dict[str, pd.DataFrame], initial_strategy: dict):
        self.data_map = historical_data_map
        self.timeline = sorted(set().union(*[df.index for df in historical_data_map.values()]))

        self.state_A = self._init_account_state("A (통제군: 타점만 갱신)", initial_strategy)
        self.state_B = self._init_account_state("B (비교군: 전략+타점 동시 갱신)", initial_strategy)
        self.magpie_graph = build_graph()

    def _init_account_state(self, name: str, strategy: dict) -> dict:
        return {
            "name": name,
            "holdings": {},
            "stats": {},
            "strategy": strategy,
            "targets": {},
            "trade_history": [],
        }

    async def run_simulation(self):
        print("🚀 [Time Machine]: A/B 시뮬레이션을 시작합니다...\n")

        if not self.timeline:
            print("⚠️ 시뮬레이션할 데이터가 없습니다.")
            return

        start_time = self.timeline[0]
        print(f"🏁 [초기화]: {start_time} 시점의 차트를 분석하여 최초 타점을 계산합니다.")

        # 최초 타점 장전 (전략 수정 없음)
        await asyncio.gather(
            self._trigger_agents(self.state_A, start_time, allow_strategy_update=False, reason="최초 타점 장전"),
            self._trigger_agents(self.state_B, start_time, allow_strategy_update=False, reason="최초 타점 장전"),
        )

        print("✅ [초기화 완료]: 첫 타점이 장전되었습니다. 타임 루프를 시작합니다!\n")

        for current_time in self.timeline:
            if current_time == start_time:
                continue

            trade_occurred_A = self._check_virtual_execution(self.state_A, current_time)
            trade_occurred_B = self._check_virtual_execution(self.state_B, current_time)

            is_9am = current_time.hour == 9
            tasks = []

            if is_9am or trade_occurred_A:
                reason = "⏰ 일봉 갱신 (09:00 정각)" if is_9am else "⚡ 매매 체결 감지 (포지션 변경)"
                tasks.append(
                    self._trigger_agents(self.state_A, current_time, allow_strategy_update=False, reason=reason)
                )

            if is_9am or trade_occurred_B:
                reason = "⏰ 일봉 갱신 (09:00 정각)" if is_9am else "⚡ 매매 체결 감지 (포지션 변경)"
                tasks.append(
                    self._trigger_agents(self.state_B, current_time, allow_strategy_update=True, reason=reason)
                )

            if tasks:
                await asyncio.gather(*tasks)

        print("\n🏁 [Time Machine]: 시뮬레이션 종료!")
        self._print_report()

    def _check_virtual_execution(self, account, current_time) -> bool:
        any_trade_occurred = False
        targets = account.get("targets", {})

        for coin, target in list(targets.items()):
            if target.get("state") in ["DONE", "EXPIRED"]:
                continue
            if coin not in self.data_map or current_time not in self.data_map[coin].index:
                continue

            candle = self.data_map[coin].loc[current_time]
            if coin not in account["stats"]:
                account["stats"][coin] = {"invested": 0, "returned": 0}

            # ⏳ 1. 만료 시간 체크
            target["hours_passed"] = target.get("hours_passed", 0) + 1
            if target["state"] == "WAITING_BUY" and target["hours_passed"] > target["valid_for_n_candles"]:
                target["state"] = "EXPIRED"
                account["trade_history"].append(f"[{current_time}] ⏳ {coin} 타점 만료")
                continue

            # 🔴 2. 매도 로직 (손절 최우선 검사)
            if target["state"] == "HOLDING" and account["holdings"].get(coin, 0) == 1:
                if self._handle_sell_logic(account, target, current_time, coin, candle):
                    any_trade_occurred = True

            # 🟢 3. 매수 로직 (매도 로직과 elif 관계 유지)
            elif target["state"] == "WAITING_BUY" and self._handle_buy_logic(
                account, target, current_time, coin, candle
            ):
                any_trade_occurred = True

        return any_trade_occurred

    def _handle_sell_logic(self, account, target, current_time, coin, candle) -> bool:
        sell_price = None
        reason = ""

        if candle["low"] <= target["loss_price"]:
            sell_price = target["loss_price"]
            reason = "🩸 손절"
        elif candle["high"] >= target["profit_price"]:
            sell_price = target["profit_price"]
            reason = "💰 익절"

        if sell_price:
            account["stats"][coin]["returned"] += sell_price
            account["holdings"][coin] = 0
            target["state"] = "DONE"
            account["trade_history"].append(f"[{current_time}] {reason} | {coin} | 1개 매도 체결: {sell_price:,.0f}원")
            return True
        return False

    def _handle_buy_logic(self, account, target, current_time, coin, candle) -> bool:
        buy_price = None
        is_bullish = candle["close"] > candle["open"]

        if target["trigger_basis"] == "TOUCH" and candle["low"] <= target["buy_upper"]:
            if candle["low"] >= target["buy_lower"]:
                buy_price = target["buy_upper"]
        elif (
            target["trigger_basis"] == "CLOSE"
            and target["buy_lower"] <= candle["close"] <= target["buy_upper"]
            and candle["volume"] >= target["min_volume"]
            and (not target["requires_bullish"] or is_bullish)
        ):
            buy_price = candle["close"]

        if buy_price:
            account["stats"][coin]["invested"] += buy_price
            account["holdings"][coin] = 1
            target["state"] = "HOLDING"
            account["trade_history"].append(f"[{current_time}] 🚀 매수 | {coin} | 1개 진입 체결: {buy_price:,.0f}원")
            return True
        return False

    async def _trigger_agents(self, account, current_time, allow_strategy_update: bool, reason: str):
        print(f"\n[{account['name']}] {reason} ➡️ LangGraph 워크플로우 가동")

        user_message = self._build_agent_user_message(account, allow_strategy_update)
        initial_state = {
            "user_id": "test_developer_001",
            "messages": [("user", user_message)],
            "owl_strategy": account["strategy"],
            "current_sim_time": current_time,
        }

        config = {"configurable": {"thread_id": f"test_simulator_{account['name']}"}}

        result_state = await self.magpie_graph.ainvoke(initial_state, config)
        self._parse_agent_results(account, result_state)

    def _build_agent_user_message(self, account, allow_strategy_update: bool) -> str:
        history_list = account["trade_history"]
        trade_history_str = "아직 체결된 매매 내역이 없습니다." if not history_list else "\n".join(history_list[-50:])

        mode_desc = "통제군(A계좌)" if not allow_strategy_update else "비교군(B계좌)"
        strategy_instruction = (
            "절대 현재 투자 전략을 수정하지 마세요."
            if not allow_strategy_update
            else "위 매매 이력을 철저히 분석하고, 시장 상황에 맞춰 필요하다면 투자 전략을 갱신하세요. 불필요하다고 판단되면 억지로 투자 전략을 갱신할 필요는 없습니다."
        )

        return (
            f"""
                {TRIGGER_PHRASE}

                [매매 이력]
                {trade_history_str}

                [시스템 지시]
                당신은 현재 {mode_desc}을 백테스트 중입니다.
                {strategy_instruction}
                기존 전략을 100% 유지한 채, [매매 이력]을 분석하여 하위 에이전트(Meerkat)가 새로운 타점을 계산할 때 주의해야 할 점을 담아 `meerkat_feedback`을 작성하고 타점 갱신을 지시하세요.
                """
            if not allow_strategy_update
            else f"""
                {TRIGGER_PHRASE}

                [매매 이력]
                {trade_history_str}

                [시스템 지시]
                당신은 현재 {mode_desc}을 백테스트 중입니다.
                {strategy_instruction}
                그 후 하위 에이전트(Meerkat)에게 [매매 이력] 분석 결과와 주의사항을 담은 `meerkat_feedback` 을 작성하여 타점 갱신을 지시하세요.
                """
        )

    def _parse_agent_results(self, account, result_state):
        for msg in reversed(result_state["messages"]):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for call in msg.tool_calls:
                    if call["name"] == "register_monitoring_targets_to_nest":
                        parsed = self._parse_target_args(call["args"])
                        if parsed:
                            account["targets"] = parsed
                            print(f"   ✅ [타점 갱신 완료]: {list(parsed.keys())}")
                    elif call["name"] == "register_strategy_to_nest":
                        # 전략 전체(코인 리스트 + 상세 내용)를 갱신
                        account["strategy"] = {
                            "target_coins": call["args"].get("target_coins"),
                            "strategy_details": call["args"].get("strategy_details"),
                        }
                        print(
                            f"   🦉 [전략 수정 완료]: {account['strategy']['target_coins']} 종목에 대해 전략이 갱신되었습니다."
                        )

    def _parse_target_args(self, args_dict) -> dict:
        target_list = args_dict.get("targets", [])
        parsed_dict = {}
        for t in target_list:
            coin = t.get("target_coin")
            parsed_dict[coin] = {
                "buy_upper": t.get("buy_price_upper_limit", 0),
                "buy_lower": t.get("buy_price_lower_limit", 0),
                "profit_price": t.get("take_profit_price", 0),
                "loss_price": t.get("stop_loss_price", 0),
                "trigger_basis": t.get("trigger_basis", "TOUCH"),
                "requires_bullish": t.get("requires_bullish_close", False),
                "min_volume": t.get("min_volume_threshold", 0),
                "valid_for_n_candles": t.get("valid_for_n_candles", 24),
                "state": t.get("state", "WAITING_BUY"),
                "hours_passed": 0,
            }
        return parsed_dict

    def _print_report(self):
        print("=" * 50)
        print("📊 [테스트 결과]")
        for account in [self.state_A, self.state_B]:
            print(f"🔹 {account['name']}")
            coin_rois = []

            for coin, stats in account["stats"].items():
                invested = stats["invested"]
                returned = stats["returned"]
                if invested == 0:
                    continue

                if account["holdings"].get(coin, 0) == 1:
                    last_price = self.data_map[coin].iloc[-1]["close"]
                    returned += last_price

                roi = ((returned - invested) / invested) * 100
                coin_rois.append(roi)
                print(
                    f"   - {coin}: 수익률 {roi:>6.2f}% (총 누적 투입: {invested:,.0f}원 / 총 누적 회수: {returned:,.0f}원)"
                )

            if coin_rois:
                avg_roi = sum(coin_rois) / len(coin_rois)
                print(f"   ➡️ 📈 전체 포트폴리오 평균 수익률: {avg_roi:+.2f}%\n")
            else:
                print("   ➡️ 📈 체결된 내역이 없습니다.\n")

            print("\n상세 거래 내역:")
            print("\n".join(account["trade_history"]))
        print("=" * 60)
