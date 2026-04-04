import asyncio

import pandas as pd
import pyupbit
import talib


async def generate_chart_context(target_coins: list[str], sim_time: str | None = None) -> str:
    """
    타겟 코인 리스트를 받아, 일봉(Macro)과 1시간봉(Micro) 데이터를 비동기로 분석하고
    LLM이 이해하기 쉬운 텍스트 리포트로 압축합니다.
    """
    print(f"   🐍 [Chart Compressor]: {target_coins}의 거시/미시 차트 데이터를 분석 중...")

    context_reports = []

    for coin in target_coins:
        df_day = await asyncio.to_thread(pyupbit.get_ohlcv, coin, interval="day", count=120, to=sim_time)
        df_hour = await asyncio.to_thread(pyupbit.get_ohlcv, coin, interval="minute60", count=72, to=sim_time)

        if df_day is None or df_day.empty or df_hour is None or df_hour.empty:
            context_reports.append(f"[{coin}] 데이터 조회 실패\n")
            continue

        report = do_chart_analyze(df_day, df_hour, coin)
        context_reports.append(report)

    return "\n".join(context_reports)


def do_chart_analyze(df_day: pd.DataFrame, df_hour: pd.DataFrame, coin: str) -> str:
    """
    일봉(Macro)과 1시간봉(Micro) 데이터프레임을 받아 하이브리드 차트 요약 리포트를 생성합니다.
    """

    if len(df_day) < 120 or len(df_hour) < 72:
        return f"[{coin}] 차트 데이터가 부족하여 기술적 분석을 수행할 수 없습니다."

    current_price = df_day["close"].iloc[-1]

    # ========================================== #
    # 🔭 1. 거시적 관점 (Macro - 일봉 기준)
    # ========================================== #

    # 1. ATR (일일 변동성)
    atr_day = talib.ATR(df_day["high"], df_day["low"], df_day["close"], timeperiod=14).iloc[-1]

    # 2. 이동평균선 (중장기 추세)
    sma_20 = talib.SMA(df_day["close"], timeperiod=20).iloc[-1]
    sma_50 = talib.SMA(df_day["close"], timeperiod=50).iloc[-1]
    sma_120 = talib.SMA(df_day["close"], timeperiod=120).iloc[-1]

    # 3. 주요 지지/저항 매물대
    support_20 = df_day["low"].rolling(window=20).min().iloc[-1]
    support_60 = df_day["low"].rolling(window=60).min().iloc[-1]
    resistance_20 = df_day["high"].rolling(window=20).max().iloc[-1]
    resistance_60 = df_day["high"].rolling(window=60).max().iloc[-1]

    # ========================================== #
    # 🔬 2. 미시적 관점 (Micro - 1시간봉 기준)
    # ========================================== #

    # 1시간 ATR (매수 영역 폭 설정용)
    atr_hour = talib.ATR(df_hour["high"], df_hour["low"], df_hour["close"], timeperiod=14).iloc[-1]

    # 단기 매물대 (최근 24시간 내 최고/최저)
    support_24_hour = df_hour["low"].rolling(window=24).min().iloc[-1]
    resistance_24_hour = df_hour["high"].rolling(window=24).max().iloc[-1]

    # 직전 3시간의 캔들 형태 분석 (휩소, 꼬리 판단용)
    recent_hours = []
    for i in range(1, 4):
        idx = -i - 1  # 현재 진행 중인 캔들을 제외하고 '확정된' 직전 캔들 3개
        row = df_hour.iloc[idx]

        recent_hours.append(f"  - {i}시간 전 마감 캔들: {row} / 거래량: {row['volume']:,.0f}")
    hourly_summary = "\n".join(recent_hours)

    # 🦦 미어캣에게 주입할 텍스트 포맷팅
    context = f"""
[📈 {coin} 하이브리드 차트 요약 리포트]

[1. 현재가]
- 현재가: {current_price:,.0f} 원

[1. 🔭 거시적 관점 (Daily - 최근 120일 기준)]
[1-1. 변동성]
- 최근 평균 변동폭(14 ATR): {atr_day:,.0f} 원
[1-2. 이동평균선]
- 20선(단기): {sma_20:,.0f} 원
- 50선(중기): {sma_50:,.0f} 원
- 120선(장기): {sma_120:,.0f} 원
[1-3. 주요 지지 및 저항 매물대]
- 20일 지지선: {support_20:,.0f} 원
- 60일 지지선: {support_60:,.0f} 원
- 20일 저항선: {resistance_20:,.0f} 원
- 60일 저항선: {resistance_60:,.0f} 원

[2. 🔬 미시적 관점 (Hourly - 최근 72시간 1시간봉 기준)]
[2-1. 변동성]
- 1시간봉 평균 변동폭(14 ATR): {atr_hour:,.0f} 원
[2-2. 단기 매물대 (최근 24시간)]
- 24시간 지지선: {support_24_hour:,.0f} 원
- 24시간 저항선: {resistance_24_hour:,.0f} 원
[2-3. 직전 3시간 캔들 형태]
- {hourly_summary}
"""

    return context
