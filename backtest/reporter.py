"""
백테스트 KPI 리포터.

BacktestResult를 받아 수익률, 승률, 샤프 지수, MDD를 계산하고
터미널에 포매팅된 리포트를 출력한다.

KPI 정의:
  - profit_rate  : (최종 자산 - 초기 자산) / 초기 자산 × 100 (%)
  - win_rate     : 수익이 난 매도 / 전체 매도 횟수 × 100 (%)
  - sharpe_ratio : 일별 수익률의 평균 / 표준편차 × √252 (연환산)
  - max_drawdown : 고점 대비 최대 낙폭 (%)
"""

from __future__ import annotations

import math
import statistics

from backtest.engine import BacktestResult, TradeRecord

# ---------------------------------------------------------------------------
# KPI 계산 함수
# ---------------------------------------------------------------------------

def _calc_profit_rate(initial: float, final_equity: float) -> float:
    return (final_equity - initial) / initial * 100.0


def _calc_win_rate(trade_records: list[TradeRecord]) -> float:
    """SELL 거래 기준 승률 계산.

    매도가 발생할 때마다, 해당 SELL 직전 BUY 단가와 비교한다.
    """
    if not trade_records:
        return 0.0

    wins = 0
    sell_count = 0
    last_buy_price: float | None = None

    for rec in trade_records:
        if rec.action == "BUY":
            last_buy_price = rec.price
        elif rec.action == "SELL" and last_buy_price is not None:
            sell_count += 1
            if rec.price > last_buy_price:
                wins += 1
            last_buy_price = None

    return (wins / sell_count * 100.0) if sell_count > 0 else 0.0


def _calc_sharpe(equity_curve: list[float]) -> float:
    """일별 수익률 기반 연환산 샤프 지수 (무위험 수익률=0 가정)."""
    if len(equity_curve) < 2:
        return 0.0

    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]

    if len(returns) < 2:
        return 0.0

    mean_r = statistics.mean(returns)
    std_r = statistics.stdev(returns)

    if std_r == 0:
        return 0.0

    return (mean_r / std_r) * math.sqrt(252)


def _calc_mdd(equity_curve: list[float]) -> float:
    """최대 낙폭 (MDD) 계산 (%)."""
    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for val in equity_curve:
        if val > peak:
            peak = val
        drawdown = (peak - val) / peak * 100.0
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


# ---------------------------------------------------------------------------
# 리포터
# ---------------------------------------------------------------------------

class BacktestReporter:
    """백테스트 결과를 KPI로 요약하고 터미널에 출력한다."""

    def __init__(self, result: BacktestResult) -> None:
        self._r = result

    def compute_kpis(self) -> dict:
        r = self._r
        return {
            "profit_rate":   _calc_profit_rate(r.initial_cash, r.final_equity),
            "win_rate":      _calc_win_rate(r.trade_records),
            "sharpe_ratio":  _calc_sharpe(r.equity_curve),
            "max_drawdown":  _calc_mdd(r.equity_curve),
            "total_trades":  len([t for t in r.trade_records if t.action == "SELL"]),
            "buy_count":     len([t for t in r.trade_records if t.action == "BUY"]),
            "total_candles": len(r.equity_curve),
        }

    def print_report(self) -> None:
        r = self._r
        kpis = self.compute_kpis()

        sep = "=" * 60
        thin = "-" * 60

        print(f"\n{sep}")
        print("  📊  PROJECT MAGPIE — BACKTEST REPORT")
        print(sep)
        print(f"  세션 ID    : {r.session_id}")
        print(f"  전략 ID    : {r.strategy_id}")
        print(f"  종목       : {r.symbol}")
        print(f"  타임프레임 : {r.interval}")
        print(f"  총 봉 수   : {kpis['total_candles']} 개")
        print(thin)
        print("  [자산 변화]")
        print(f"  초기 자산  : {r.initial_cash:>15,.2f}")
        print(f"  최종 자산  : {r.final_equity:>15,.2f}")
        print(f"  현금 잔고  : {r.final_cash:>15,.2f}")
        print(thin)
        print("  [KPI]")
        profit_icon = "📈" if kpis["profit_rate"] >= 0 else "📉"
        print(f"  수익률     : {profit_icon} {kpis['profit_rate']:>+10.2f} %")
        print(f"  승률       : {'🏆' if kpis['win_rate'] >= 50 else '💀'}  {kpis['win_rate']:>10.2f} %")
        print(f"  샤프 지수  : {'✅' if kpis['sharpe_ratio'] >= 1 else '⚠️ '} {kpis['sharpe_ratio']:>10.4f}")
        print(f"  최대 낙폭  : 🩸 {kpis['max_drawdown']:>10.2f} %")
        print(thin)
        print("  [거래 통계]")
        print(f"  매수 횟수  : {kpis['buy_count']:>5} 회")
        print(f"  매도 횟수  : {kpis['total_trades']:>5} 회")
        print(thin)
        if r.trade_records:
            print("  [최근 5개 거래]")
            for rec in r.trade_records[-5:]:
                icon = "🟢" if rec.action == "BUY" else "🔴"
                print(
                    f"  {icon} {rec.action:<4} [{rec.timestamp[:10]}] "
                    f"price={rec.price:>12,.0f}  qty={rec.quantity:.6f}"
                )
        print(sep)
        print()

    def return_kpis(self) -> dict:
        """업데이트용 KPI dict 반환 (db_tools.update_strategy_performance 인자 형식)."""
        kpis = self.compute_kpis()
        return {
            "profit_rate":  round(kpis["profit_rate"],  4),
            "win_rate":     round(kpis["win_rate"],     4),
            "sharpe_ratio": round(kpis["sharpe_ratio"], 4),
            "max_drawdown": round(kpis["max_drawdown"], 4),
            "total_trades": kpis["total_trades"],
        }
