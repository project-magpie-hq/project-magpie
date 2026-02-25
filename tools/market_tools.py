import talib
import yfinance as yf
from langchain_core.tools import tool


@tool
def get_ticker_ohlcv(ticker: str, interval: str = "1d", period: str = "3mo") -> str:
    """
    yfinance를 사용해 특정 주식/ETF/암호화폐의 OHLCV 틱 데이터를 가져옵니다.

    Args:
        ticker: 종목 코드 (예: 'AAPL', 'BTC-USD', '005930.KS', 'SPY')
        interval: 봉 주기 (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
                  ※ 1m~30m은 최근 7일, 1h~90m은 최근 60일 내 데이터만 조회 가능
        period:   조회 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max)
    """
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        return f"❌ '{ticker}' 데이터를 찾을 수 없습니다. 종목 코드와 interval/period 조합을 확인해주세요."

    # MultiIndex 컬럼 평탄화 (yfinance 0.2+ 대응)
    if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, "droplevel"):
        try:
            df.columns = df.columns.droplevel(1)
        except Exception:
            pass

    recent = df.tail(20)
    return (
        f"📊 [{ticker}] OHLCV 데이터 ({interval} 봉 / 조회기간: {period})\n"
        f"총 {len(df)}개 봉 | 최근 20개 표시:\n\n"
        f"{recent.to_string()}"
    )


@tool
def calculate_technical_indicators(ticker: str, interval: str = "1d", period: str = "1y") -> str:
    """
    yfinance로 OHLCV 데이터를 가져와 ta-lib으로 주요 기술적 지표를 계산하고 수치를 반환합니다.

    계산 지표: RSI(14), MACD(12/26/9), 볼린저밴드(20,2σ), EMA(20/50/200), 스토캐스틱(14,3,3), ADX(14)

    Args:
        ticker: 종목 코드 (예: 'AAPL', 'BTC-USD', '005930.KS')
        interval: 봉 주기 (1d, 1wk, 1h 등)
        period:   조회 기간 (3mo, 6mo, 1y, 2y)
                  ※ EMA200 계산을 위해 최소 200개 봉이 필요합니다. 일봉이면 1y 이상 권장
    """
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        return f"❌ '{ticker}' 데이터를 찾을 수 없습니다."

    # MultiIndex 컬럼 평탄화
    if hasattr(df.columns, "droplevel"):
        try:
            df.columns = df.columns.droplevel(1)
        except Exception:
            pass

    close = df["Close"].squeeze().astype(float).values
    high = df["High"].squeeze().astype(float).values
    low = df["Low"].squeeze().astype(float).values

    if len(close) < 30:
        return f"❌ 데이터가 부족합니다 (현재 {len(close)}개). period를 늘려주세요."

    # --- 지표 계산 ---
    rsi = talib.RSI(close, timeperiod=14)
    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    bb_upper, bb_middle, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    ema20 = talib.EMA(close, timeperiod=20)
    ema50 = talib.EMA(close, timeperiod=50)
    ema200 = talib.EMA(close, timeperiod=200)
    slowk, slowd = talib.STOCH(high, low, close, fastk_period=14, slowk_period=3, slowd_period=3)
    adx = talib.ADX(high, low, close, timeperiod=14)

    cur = close[-1]

    def fmt(v, d=4):
        return f"{v:.{d}f}" if v == v else "N/A"  # NaN 처리

    # RSI 해석
    rsi_val = rsi[-1]
    if rsi_val != rsi_val:
        rsi_interp = "데이터 부족"
    elif rsi_val > 70:
        rsi_interp = "과매수 구간 (70 초과) ⚠️"
    elif rsi_val < 30:
        rsi_interp = "과매도 구간 (30 미만) 🔥"
    else:
        rsi_interp = "중립 구간 (30~70)"

    # MACD 해석
    macd_interp = "골든크로스 (상승 신호) 📈" if macd[-1] > macd_signal[-1] else "데드크로스 (하락 신호) 📉"

    # BB 위치
    if cur > bb_upper[-1]:
        bb_pos = "상단 돌파 (과매수 영역)"
    elif cur < bb_lower[-1]:
        bb_pos = "하단 이탈 (과매도 영역)"
    else:
        bb_pos = "밴드 내부"
    bb_width = ((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]) * 100

    # EMA 정배열
    if ema200[-1] == ema200[-1]:  # NaN 아닌 경우
        ema_align = "✅ 정배열 (EMA20>EMA50>EMA200)" if ema20[-1] > ema50[-1] > ema200[-1] else "❌ 역배열 또는 혼조"
    else:
        ema_align = "EMA200 계산 불가 (데이터 부족)"

    # Stochastic 해석
    stoch_val = slowk[-1]
    if stoch_val != stoch_val:
        stoch_interp = "데이터 부족"
    elif stoch_val > 80:
        stoch_interp = "과매수 구간 (80 초과)"
    elif stoch_val < 20:
        stoch_interp = "과매도 구간 (20 미만)"
    else:
        stoch_interp = "중립 구간"

    # ADX 해석
    adx_val = adx[-1]
    adx_interp = f"강한 추세 (ADX>{adx_val:.0f})" if adx_val > 25 else f"약한 추세 / 횡보 (ADX={adx_val:.1f})"

    result = f"""📈 [{ticker}] 기술적 지표 분석 결과 ({interval} / {period})
현재가: {fmt(cur)} | 데이터 {len(close)}개 봉

━━━ RSI (14) ━━━━━━━━━━━━━━━━━━━━━━━━━
• 값: {fmt(rsi_val, 2)}
• 해석: {rsi_interp}

━━━ MACD (12, 26, 9) ━━━━━━━━━━━━━━━━━
• MACD:      {fmt(macd[-1])}
• Signal:    {fmt(macd_signal[-1])}
• Histogram: {fmt(macd_hist[-1])}
• 해석: {macd_interp}

━━━ 볼린저 밴드 (20, 2σ) ━━━━━━━━━━━━━
• 상단: {fmt(bb_upper[-1])}
• 중간(MA20): {fmt(bb_middle[-1])}
• 하단: {fmt(bb_lower[-1])}
• 현재 위치: {bb_pos}
• 밴드 폭 (변동성): {bb_width:.2f}%

━━━ 이동평균선 (EMA) ━━━━━━━━━━━━━━━━━
• EMA20:  {fmt(ema20[-1])}
• EMA50:  {fmt(ema50[-1])}
• EMA200: {fmt(ema200[-1])}
• 정배열: {ema_align}

━━━ 스토캐스틱 (14, 3, 3) ━━━━━━━━━━━
• %K: {fmt(slowk[-1], 2)}
• %D: {fmt(slowd[-1], 2)}
• 해석: {stoch_interp}

━━━ ADX (14) ━━━━━━━━━━━━━━━━━━━━━━━━
• 값: {fmt(adx_val, 2)}
• 추세 강도: {adx_interp}"""

    return result.strip()


@tool
def request_chart_analysis(ticker: str, interval: str = "1d", period: str = "1y") -> str:
    """
    Meerkat Scanner 서브 에이전트에게 특정 종목의 기술적 지표 계산 및 트레이딩 관점 해석을 요청합니다.
    사용자가 특정 주식/코인의 기술적 분석, 차트 분석, 매수/매도 타이밍, 지표 확인을 요청할 때 호출하세요.

    Args:
        ticker: 종목 코드 (예: 'AAPL', 'BTC-USD', '005930.KS', 'ETH-USD')
        interval: 봉 주기 (1h, 1d, 1wk 등) - 기본값 1d
        period:   조회 기간 (3mo, 6mo, 1y, 2y) - 기본값 1y
    """
    # 이 함수는 handoff 시그널 역할을 합니다.
    # 실제 실행은 LangGraph의 meerkat_scanner_node가 담당합니다.
    return f"{ticker} 차트 분석 요청이 Meerkat Scanner에게 전달되었습니다."
