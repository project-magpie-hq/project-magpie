import time
from datetime import datetime

import pandas as pd
import pyupbit


def fetch_historical_candles(ticker: str, days: int = 30) -> pd.DataFrame:
    """
    업비트 API를 Pagination하여 특정 기간(days) 동안의 1시간 캔들을 수집합니다.
    """
    # 1일 = 24시간 (1시간 캔들 24개)
    total_candles = days * 24

    dfs = []
    to_date = datetime.now()

    while total_candles > 0:
        # 한 번에 최대 200개까지만 요청 가능
        count = min(total_candles, 200)

        # to_date를 기준으로 과거 count개 만큼의 캔들을 가져옴
        df = pyupbit.get_ohlcv(ticker, interval="minute60", count=count, to=to_date)

        if df is None or df.empty:
            print(f"   ⚠️ [{ticker}] 더 이상 불러올 데이터가 없습니다.")
            break

        dfs.append(df)

        # 다음 요청을 위해 to_date를 현재 가져온 데이터의 가장 오래된 시간으로 갱신
        to_date = df.index[0]
        total_candles -= count

        # 업비트 API 초당 요청 제한(Rate Limit) 방지용 딜레이
        time.sleep(0.2)

    if not dfs:
        return pd.DataFrame()

    # 수집한 여러 개의 데이터프레임을 하나로 합침
    result_df = pd.concat(dfs)

    # 중복된 캔들 제거 및 시간순(과거->현재)으로 정렬
    result_df = result_df[~result_df.index.duplicated(keep="first")]
    result_df.sort_index(inplace=True)

    return result_df
