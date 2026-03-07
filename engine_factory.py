"""
engine_factory.py — 모드에 따라 적합한 엔진을 반환하는 팩토리.

사용 예::

    from engine_factory import create_engine
    from backtest.engine import EngineConfig
    from providers.base import ProviderMode

    config = EngineConfig(
        symbol="KRW-BTC",
        style="balanced",
        user_prompt="비트코인 균형 매매",
        mode=ProviderMode.BACKTEST,   # ← 여기만 바꾸면 전환
    )
    engine = create_engine(config)
    await engine.run(config)        # BacktestEngine 또는 LiveEngine 자동 선택
"""

from __future__ import annotations

from typing import Union

from backtest.engine import BacktestEngine, EngineConfig
from live.engine import LiveEngine
from providers.base import ProviderMode


def create_engine(config: EngineConfig) -> Union[BacktestEngine, LiveEngine]:
    """config.mode에 따라 BacktestEngine 또는 LiveEngine을 반환한다.

    Args:
        config: 실행 설정. ``mode`` 필드가 판단 기준이다.

    Returns:
        - ``ProviderMode.BACKTEST`` → :class:`BacktestEngine`
        - ``ProviderMode.REAL``     → :class:`LiveEngine`

    Raises:
        ValueError: 알 수 없는 mode 값일 경우.
    """
    if config.mode == ProviderMode.BACKTEST:
        return BacktestEngine()
    elif config.mode == ProviderMode.REAL:
        return LiveEngine()
    else:
        raise ValueError(f"알 수 없는 모드: {config.mode!r}")
