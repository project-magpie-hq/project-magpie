from pydantic import BaseModel, Field


class HawkCandidatesInput(BaseModel):
    target_coins: list[str] = Field(
        description="1차 선정한 후보 코인 티커 리스트 (예: ['KRW-BTC', 'KRW-SOL', 'KRW-ETH']). 차트 분석이 필요한 후보들을 최소 1개, 최대 10개까지 지정할 수 있습니다.",
        min_length=1,
        max_length=10,
    )


class UpdateTargetCoinsInput(BaseModel):
    target_coins: list[str] = Field(
        description="최종 선정된 타겟 코인 티커 리스트 (예: ['KRW-BTC', 'KRW-SOL']). 반드시 1개 이상, 최대 5개까지만 지정해야 합니다.",
        min_length=1,
        max_length=5,
    )
