from pydantic import BaseModel, Field


class FoxCandidatesInput(BaseModel):
    target_coins: list[str] = Field(
        description="Fox Finder가 1차 선정한 후보 코인 티커 리스트 (예: ['KRW-BTC', 'KRW-SOL', 'KRW-ETH', ...]). "
        "차트 분석(Meerkat)과 타점 계산(Calculate Team)이 필요한 후보들을 최소 5개, 최대 20개까지 지정할 수 있습니다.",
        min_length=1,
        max_length=20,
    )
