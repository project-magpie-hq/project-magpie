import time
from datetime import datetime

import pandas as pd
import pyupbit


def fetch_historical_candles_by_range(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    지정된 기간(start_date ~ end_date)의 1시간 캔들을 수집합니다.
    (형식: 'YYYY-MM-DD HH:MM:SS')
    """

    start_dt = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")

    dfs = []
    to_date_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    to_date_obj = end_dt

    while to_date_obj > start_dt:
        df = pyupbit.get_ohlcv(ticker, interval="minute60", count=200, to=to_date_str)

        if df is None or df.empty:
            break

        dfs.append(df)

        oldest_candle_time = df.index[0]
        to_date_obj = oldest_candle_time - pd.Timedelta(hours=1)
        to_date_str = to_date_obj.strftime("%Y-%m-%d %H:%M:%S")

        time.sleep(0.2)

    if not dfs:
        return pd.DataFrame()

    result_df = pd.concat(dfs)
    result_df = result_df[~result_df.index.duplicated(keep="first")]
    result_df.sort_index(inplace=True)

    result_df = result_df[(result_df.index >= start_dt) & (result_df.index <= end_dt)]

    return result_df
