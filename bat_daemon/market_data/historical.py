import time
from datetime import datetime
from math import ceil
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd
import pyupbit

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


def fetch_historical_candles_by_range(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    interval: str = "minute1",
    on_batch: Callable[[int, datetime], None] | None = None,
) -> pd.DataFrame:
    """
    지정된 기간(start_date ~ end_date)의 분봉/시간봉 캔들을 수집합니다.
    형식: 'YYYY-MM-DD HH:MM:SS'
    """

    start_dt = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
    interval_step = _interval_step(interval)
    estimated_total_batches = estimate_historical_batches(start_date, end_date, interval=interval)
    max_batches = max(estimated_total_batches + 10, 20)

    dfs = []
    to_date_obj = end_dt
    to_date_str = _kst_naive_to_utc_string(to_date_obj)
    batch_count = 0
    previous_oldest_candle_time: pd.Timestamp | None = None

    while to_date_obj > start_dt:
        if batch_count >= max_batches:
            raise RuntimeError(
                f"[{ticker}] 과거 캔들 로드가 예상 배치 수를 비정상적으로 초과했습니다. "
                f"interval={interval}, estimated_batches={estimated_total_batches}, actual_batches={batch_count}"
            )

        df = pyupbit.get_ohlcv(ticker, interval=interval, count=200, to=to_date_str)

        if df is None or df.empty:
            break

        dfs.append(df)
        batch_count += 1

        oldest_candle_time = df.index[0]
        if previous_oldest_candle_time is not None and oldest_candle_time >= previous_oldest_candle_time:
            raise RuntimeError(
                f"[{ticker}] 과거 캔들 로드 중 시간 역행이 멈췄습니다. "
                f"interval={interval}, batch={batch_count}, oldest={oldest_candle_time}, "
                f"previous_oldest={previous_oldest_candle_time}"
            )

        if on_batch is not None:
            on_batch(batch_count, oldest_candle_time.to_pydatetime())
        previous_oldest_candle_time = oldest_candle_time
        to_date_obj = oldest_candle_time.to_pydatetime() - interval_step
        to_date_str = _kst_naive_to_utc_string(to_date_obj)

        time.sleep(0.2)

    if not dfs:
        return pd.DataFrame()

    result_df = pd.concat(dfs)
    result_df = result_df[~result_df.index.duplicated(keep="first")]
    result_df.sort_index(inplace=True)

    result_df = result_df[(result_df.index >= start_dt) & (result_df.index <= end_dt)]

    return result_df


def estimate_historical_batches(start_date: str, end_date: str, *, interval: str = "minute1", batch_size: int = 200) -> int:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
    interval_step = _interval_step(interval)
    total_steps = max(0, int((end_dt - start_dt) / interval_step))
    return ceil(total_steps / batch_size) if total_steps > 0 else 0


def _kst_naive_to_utc_string(value: datetime) -> str:
    return value.replace(tzinfo=KST).astimezone(UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _interval_step(interval: str) -> pd.Timedelta:
    if interval == "minute1":
        return pd.Timedelta(minutes=1)
    if interval == "minute3":
        return pd.Timedelta(minutes=3)
    if interval == "minute5":
        return pd.Timedelta(minutes=5)
    if interval == "minute10":
        return pd.Timedelta(minutes=10)
    if interval == "minute15":
        return pd.Timedelta(minutes=15)
    if interval == "minute30":
        return pd.Timedelta(minutes=30)
    if interval == "minute60":
        return pd.Timedelta(hours=1)
    if interval == "minute240":
        return pd.Timedelta(hours=4)
    if interval == "day":
        return pd.Timedelta(days=1)
    raise ValueError(f"지원하지 않는 interval 입니다: {interval}")
