from pydantic import BaseModel, Field


class UpdateTargetCoinsInput(BaseModel):
    target_coins: list[str] = Field(
        description="최종 선정된 타겟 코인 티커 리스트 (예: ['KRW-BTC', 'KRW-SOL']). 반드시 1개 이상, 최대 5개까지만 지정해야 합니다.",
        min_length=1,
        max_length=5,
    )
