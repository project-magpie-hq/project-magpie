from enum import StrEnum

from pydantic import BaseModel, Field


class TriggerBasis(StrEnum):
    TOUCH = "TOUCH"
    CLOSE = "CLOSE"


class TargetSchema(BaseModel):
    target_coin: str = Field(
        description="투자할 타겟 코인 티커 (예: 'KRW-BTC', 'KRW-SOL'). 반드시 업비트 티커 형식으로 작성"
    )

    # [가격 조건 - 매수]
    buy_price_upper_limit: float = Field(
        description="추격 매수(FOMO)를 방지하는 매수 허용 상한선. 이 가격 위로는 절대 사지 마라."
    )
    buy_price_lower_limit: float = Field(
        description="투매를 방지하는 매수 허용 하한선. 이 가격 밑으로 빠지면 매수 취소."
    )
    # [가격 조건 - 매도]
    take_profit_price: float = Field(description="익절 목표가")
    stop_loss_price: float = Field(description="손절 방어선")

    # [캔들 조건]
    trigger_basis: TriggerBasis = Field(
        description="TOUCH는 꼬리 도달 시 즉시 체결, CLOSE는 1시간 캔들 종가 확정 시 체결"
    )
    min_volume_threshold: float = Field(description="신뢰할 수 있는 돌파/반등을 위한 최소 1시간 거래량")
    requires_bullish_close: bool = Field(description="매수 시, 해당 1시간 캔들이 양봉으로 마감해야만 진입할지 여부")
    valid_for_n_candles: int = Field(description="이 타점이 유효한 캔들 개수 (예: 24 = 24시간 뒤 폐기)")

    reason: str = Field(description="장기 추세와 최근 3일의 단기 흐름을 종합하여 이 타점을 도출한 근거 (100자 이내)")


class MonitoringTargets(BaseModel):
    targets: list[TargetSchema] = Field(description="계산된 각 코인별 타점 리스트")
