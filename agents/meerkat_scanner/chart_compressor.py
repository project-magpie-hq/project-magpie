import asyncio
import logging

import pandas as pd
import pyupbit
import talib

logger = logging.getLogger(__name__)

# 차트 분석 파라미터 상수
DAY_CANDLE_COUNT = 120
HOUR_CANDLE_COUNT = 72
ATR_PERIOD = 14


async def generate_chart_context(target_coins: list[str], sim_time: str | None = None) -> str:
    """
    타겟 코인 리스트를 받아, 일봉(Macro)과 1시간봉(Micro) 데이터를 비동기로 분석하고
    LLM이 이해하기 쉬운 텍스트 리포트로 압축합니다.
    """
    print(f"   🐍 [Chart Compressor]: {target_coins}의 거시/미시 차트 데이터를 분석 중...")

    context_reports: list[str] = []

    for coin in target_coins:
        try:
            df_day = await asyncio.to_thread(
                pyupbit.get_ohlcv, coin, interval="day", count=DAY_CANDLE_COUNT, to=sim_time
            )
            df_hour = await asyncio.to_thread(
                pyupbit.get_ohlcv, coin, interval="minute60", count=HOUR_CANDLE_COUNT, to=sim_time
            )
        except Exception as e:
            logger.exception("[%s] 차트 데이터 API 호출 실패", coin)
            context_reports.append(f"[{coin}] 데이터 조회 실패: {e}\n")
            continue

        if df_day is None or df_day.empty or df_hour is None or df_hour.empty:
            logger.warning("[%s] 차트 데이터가 비어 있습니다.", coin)
            context_reports.append(f"[{coin}] 데이터 조회 실패\n")
            continue

        try:
            report = do_chart_analyze(df_day, df_hour, coin)
        except Exception as e:
            logger.exception("[%s] 차트 분석 실패", coin)
            context_reports.append(f"[{coin}] 차트 분석 중 오류 발생: {e}\n")
            continue

        context_reports.append(report)

    return "\n".join(context_reports)


def do_chart_analyze(df_day: pd.DataFrame, df_hour: pd.DataFrame, coin: str) -> str:
    """
    일봉(Macro)과 1시간봉(Micro) 데이터프레임을 받아 하이브리드 차트 요약 리포트를 생성합니다.
    """
    if len(df_day) < DAY_CANDLE_COUNT or len(df_hour) < HOUR_CANDLE_COUNT:
        return f"[{coin}] 차트 데이터가 부족하여 기술적 분석을 수행할 수 없습니다."

    current_price: float = df_day["close"].iloc[-1]

    # ========================================== #
    # 🔭 1. 거시적 관점 (Macro - 일봉 기준)
    # ========================================== #

    # 1. ATR (일일 변동성)
    atr_day: float = talib.ATR(
        df_day["high"].astype(float).values,
        df_day["low"].astype(float).values,
        df_day["close"].astype(float).values,
        timeperiod=ATR_PERIOD,
    )[-1]

    # 2. 이동평균선 (중장기 추세)
    sma_20: float = talib.SMA(df_day["close"].astype(float).values, timeperiod=20)[-1]
    sma_50: float = talib.SMA(df_day["close"].astype(float).values, timeperiod=50)[-1]
    sma_120: float = talib.SMA(df_day["close"].astype(float).values, timeperiod=120)[-1]

    # 3. 주요 지지/저항 매물대
    support_20: float = df_day["low"].rolling(window=20).min().iloc[-1]
    support_60: float = df_day["low"].rolling(window=60).min().iloc[-1]
    resistance_20: float = df_day["high"].rolling(window=20).max().iloc[-1]
    resistance_60: float = df_day["high"].rolling(window=60).max().iloc[-1]

    # ========================================== #
    # 🔬 2. 미시적 관점 (Micro - 1시간봉 기준)
    # ========================================== #

    # 1시간 ATR (매수 영역 폭 설정용)
    atr_hour: float = talib.ATR(
        df_hour["high"].astype(float).values,
        df_hour["low"].astype(float).values,
        df_hour["close"].astype(float).values,
        timeperiod=ATR_PERIOD,
    )[-1]

    # 단기 매물대 (최근 24시간 내 최고/최저)
    support_24_hour: float = df_hour["low"].rolling(window=24).min().iloc[-1]
    resistance_24_hour: float = df_hour["high"].rolling(window=24).max().iloc[-1]

    # 직전 3시간의 캔들 형태 분석 (휩소, 꼬리 판단용)
    recent_hours: list[str] = []
    for i in range(1, 3 + 1):
        idx = -i - 1  # 현재 진행 중인 캔들을 제외하고 '확정된' 직전 캔들 3개
        row = df_hour.iloc[idx]
        recent_hours.append(f"  - {i}시간 전 마감 캔들: {row} / 거래량: {row['volume']:,.0f}")
    hourly_summary = "\n".join(recent_hours)

    # 🦦 미어캣에게 주입할 텍스트 포맷팅
    context = f"""
[📈 {coin} 하이브리드 차트 요약 리포트]

[1. 현재가]
- 현재가: {current_price:,.0f} 원

[1. 🔭 거시적 관점 (Daily - 최근 {DAY_CANDLE_COUNT}일 기준)]
[1-1. 변동성]
- 최근 평균 변동폭({ATR_PERIOD} ATR): {atr_day:,.0f} 원
[1-2. 이동평균선]
- 20선(단기): {sma_20:,.0f} 원
- 50선(중기): {sma_50:,.0f} 원
- 120선(장기): {sma_120:,.0f} 원
[1-3. 주요 지지 및 저항 매물대]
- 20일 지지선: {support_20:,.0f} 원
- 60일 지지선: {support_60:,.0f} 원
- 20일 저항선: {resistance_20:,.0f} 원
- 60일 저항선: {resistance_60:,.0f} 원

[2. 🔬 미시적 관점 (Hourly - 최근 {HOUR_CANDLE_COUNT}시간 1시간봉 기준)]
[2-1. 변동성]
- 1시간봉 평균 변동폭({ATR_PERIOD} ATR): {atr_hour:,.0f} 원
[2-2. 단기 매물대 (최근 24시간)]
- 24시간 지지선: {support_24_hour:,.0f} 원
- 24시간 저항선: {resistance_24_hour:,.0f} 원
[2-3. 직전 3시간 캔들 형태]
- {hourly_summary}
"""

    return context
