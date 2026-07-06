"""Calculate Team 데이터 준비 노드

Calculate Team 서브그래프 진입 시 Bull/Bear/Dolphin이 사용할 컨텍스트 데이터를
DB에서 조회하여 상태에 설정한다. 이미 값이 설정되어 있으면 건너뛴다.
"""

import logging
from typing import Any

from magpie_agent.agents.calculate_team.schema import CalculateTeamState
from magpie_agent.tools.monitor_target import fetch_monitoring_targets_by_user
from magpie_agent.tools.strategy import fetch_strategy_by_user
from magpie_agent.tools.wallet import fetch_wallet_by_user

logger = logging.getLogger(__name__)


async def prepare_calculate_data(state: CalculateTeamState) -> dict[str, Any]:
    """Calculate Team 실행 전 필요한 모든 컨텍스트 데이터를 DB에서 조회한다.

    Bull/Bear/Dolphin이 타점 계산에 사용할 데이터를 준비하며,
    이미 값이 설정되어 있으면 건너뛴다.
    """
    print("   📦 [Calc Prepare]: Bull/Bear/Dolphin 컨텍스트 데이터를 준비합니다...")

    user_id = state.get("user_id")

    # 1. 차트 분석 리포트 — messages 마지막 항목에서 추출
    chart_context = state.get("chart_context") or ""
    if not chart_context:
        messages = state.get("messages", [])
        msg_debug = f"messages={len(messages)}개"
        if messages:
            last = messages[-1]
            last_content = str(getattr(last, "content", "") or "")[:80]
            msg_debug += f", 마지막 msg type={type(last).__name__}, content='{last_content}...'"
            if hasattr(last, "content"):
                chart_context = str(last.content) if last.content else ""
            if not chart_context:
                msg_debug += " → content empty"
        chart_context_src = "(messages fallback)"
        print(f"   🔍 [Debug]: chart_context={chart_context is not None}, len={len(chart_context) if chart_context else 0}, src={chart_context_src}, {msg_debug}" if chart_context else f"   🔍 [Debug]: chart_context=EMPTY/None, src={chart_context_src}, {msg_debug}")
        if not chart_context:
            chart_context = "(차트 분석 없음)"
            print("   🔍 [Debug]: chart_context → '(차트 분석 없음)' 으로 fallback")
    else:
        print(f"   🔍 [Debug]: chart_context={len(chart_context)}자 from state 직접 전달, 앞 80자: '{chart_context[:80]}...'")

    # 2. 전략 정보 + 타겟 코인 목록
    strategy_details = state.get("strategy_details")
    target_coins = state.get("target_coins")
    if not target_coins:
        current_target_coin = state.get("current_target_coin")
        print(f"   🔍 [Debug]: target_coins=None, current_target_coin='{current_target_coin}'")
        if current_target_coin:
            target_coins = str([current_target_coin])
            print(f"   🔍 [Debug]: target_coins 협소화 → {target_coins}")
        elif user_id:
            try:
                strategy = await fetch_strategy_by_user(user_id)
                if strategy:
                    strategy_details = strategy_details or str(strategy.get("strategy_details", {}))
                    target_coins = str(strategy.get("target_coins", []))
                    print(f"   🔍 [Debug]: target_coins 전략 DB fallback → {target_coins}")
            except Exception as e:
                logger.warning("전략 정보 조회 실패 (user_id: %s): %s", user_id, e)
    else:
        print(f"   🔍 [Debug]: target_coins='{target_coins}' (state에 이미 있음)")
    if not strategy_details:
        strategy_details = "(정보 없음)"
    if not target_coins:
        target_coins = "(없음)"
        print(f"   🔍 [Debug]: target_coins → '(없음)' 으로 최종 fallback")

    # 3. 지갑 정보
    wallet_data = state.get("wallet_data")
    if not wallet_data and user_id:
        try:
            wallet = await fetch_wallet_by_user(user_id)
            if wallet:
                wallet_data = str(wallet.model_dump())
        except Exception as e:
            logger.warning("지갑 정보 조회 실패 (user_id: %s): %s", user_id, e)
    if not wallet_data:
        wallet_data = "(없음)"

    # 4. 기존 타점 정보
    existing_targets_clean = state.get("existing_targets_clean")
    if not existing_targets_clean and user_id:
        try:
            existing_targets = await fetch_monitoring_targets_by_user(user_id)
            if existing_targets:
                clean = []
                for t in existing_targets:
                    clean.append(
                        {
                            k: t.get(k)
                            for k in (
                                "target_coin",
                                "status",
                                "buy_price_upper_limit",
                                "buy_price_lower_limit",
                                "take_profit_price",
                                "stop_loss_price",
                                "buy_allocation_pct",
                            )
                        }
                    )
                existing_targets_clean = str(clean)
        except Exception as e:
            logger.warning("타점 정보 조회 실패 (user_id: %s): %s", user_id, e)
    if not existing_targets_clean:
        existing_targets_clean = "(없음)"

    # 5. 최근 매매 기록 — 지갑의 trade_history에서 추출
    recent_trades = state.get("recent_trades")
    if not recent_trades and user_id:
        try:
            wallet = await fetch_wallet_by_user(user_id)
            if wallet and hasattr(wallet, "trade_history") and wallet.trade_history:
                trades = []
                for trade_entry in wallet.trade_history[-10:]:  # 최근 10건
                    trades.append(
                        {
                            "market": trade_entry.market,
                            "signal": trade_entry.signal.value if hasattr(trade_entry.signal, "value") else str(trade_entry.signal),
                            "price": trade_entry.price,
                            "volume": trade_entry.volume,
                            "total_price": trade_entry.total_price,
                            "executed_at": str(trade_entry.executed_at),
                        }
                    )
                recent_trades = str(trades)
        except Exception as e:
            logger.warning("매매 기록 조회 실패 (user_id: %s): %s", user_id, e)
    if not recent_trades:
        recent_trades = "(없음)"

    # 6. 피드백 데이터
    feedback_data = state.get("feedback_data")
    if not feedback_data:
        feedback_data = "(없음)"

    # 7. Daemon에서 전달된 트리거 정보 (어떤 코인, 가격, 사유)
    trigger_info = state.get("trigger_info")
    if not trigger_info:
        trigger_info = "(없음)"

    print("   ✅ [Calc Prepare]: 컨텍스트 데이터 준비 완료")

    return {
        "chart_context": chart_context,
        "strategy_details": strategy_details,
        "wallet_data": wallet_data,
        "existing_targets_clean": existing_targets_clean,
        "recent_trades": recent_trades,
        "feedback_data": feedback_data,
        "trigger_info": trigger_info,
        "target_coins": target_coins,
    }
