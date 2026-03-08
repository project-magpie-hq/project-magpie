import pandas as pd
import pyupbit
import talib


def generate_chart_context(target_coins: list[str]) -> str:
    """
    타겟 코인 리스트를 받아, 각 코인의 실시간 차트 데이터를 분석하고
    LLM이 이해하기 쉬운 텍스트 리포트로 압축합니다.
    """
    print(f"   🐍 [Chart Compressor]: {target_coins}의 실시간 차트 데이터를 분석 중...")

    context_reports = []

    for coin in target_coins:
        df = pyupbit.get_ohlcv(coin, interval="day", count=120)

        if df is None or df.empty:
            context_reports.append(f"[{coin}] 데이터 조회 실패\n")
            continue

        report = do_chart_analyze(df)
        context_reports.append(report)

    return "\n".join(context_reports)


def do_chart_analyze(df: pd.DataFrame) -> str:
    """
    OHLCV 데이터프레임을 받아 LLM이 이해하기 쉬운 텍스트 형태의 '차트 요약 리포트'로 압축합니다.
    """
    # 최소 120개의 캔들이 있어야 120일(봉)선 등을 계산할 수 있음
    if len(df) < 120:
        return "차트 데이터가 부족하여 기술적 분석을 수행할 수 없습니다."

    current_price = df["close"].iloc[-1]

    # 1. ATR (변동성) 계산: 노이즈 필터링 및 손절 기준
    atr = talib.ATR(df["high"], df["low"], df["close"], timeperiod=14).iloc[-1]

    # 2. 이동평균선 계산: 현재 가격이 추세의 어디쯤 있는지 파악
    sma_20 = talib.SMA(df["close"], timeperiod=20).iloc[-1]
    sma_50 = talib.SMA(df["close"], timeperiod=50).iloc[-1]
    sma_120 = talib.SMA(df["close"], timeperiod=120).iloc[-1]

    # 3. 지지선/저항선 계산 (Rolling Min/Max 활용)
    # 복잡한 피봇 연산 대신 최근 N개 봉의 최저/최고점을 강력한 지지/저항으로 간주
    support_20 = df["low"].rolling(window=20).min().iloc[-1]
    support_60 = df["low"].rolling(window=60).min().iloc[-1]
    resistance_20 = df["high"].rolling(window=20).max().iloc[-1]
    resistance_60 = df["high"].rolling(window=60).max().iloc[-1]

    # 🦦 미어캣에게 주입할 텍스트 포맷팅
    context = f"""
[현재 차트 요약 리포트]
- 현재가: {current_price:,.0f} 원
- 최근 평균 변동폭(14 ATR): {atr:,.0f} 원 (손절선 설정 시 노이즈 방어용으로 참고)

[주요 이동평균선 위치]
- 20선(단기): {sma_20:,.0f} 원
- 50선(중기): {sma_50:,.0f} 원
- 120선(장기): {sma_120:,.0f} 원

[주요 지지선 및 저항선]
- 단기 지지선 (최근 20봉 바닥): {support_20:,.0f} 원
- 장기 지지선 (최근 60봉 바닥): {support_60:,.0f} 원
- 단기 저항선 (최근 20봉 천장): {resistance_20:,.0f} 원
- 장기 저항선 (최근 60봉 천장): {resistance_60:,.0f} 원
"""
    return context
