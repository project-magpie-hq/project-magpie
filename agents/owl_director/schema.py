from typing import Any

from pydantic import BaseModel, Field, field_validator


# discussion. DB에 들어갈 떄 created_at이나 user_id 같은게 들어가는데 DB 저장되는 스키마도 있으면 편할 듯? 구현은 어케할지 모르겠음
class StrategySchema(BaseModel):
    target_coins: list[str] = Field(
        description="투자할 타겟 코인 티커 리스트 (예: ['KRW-BTC', 'KRW-SOL']). 반드시 1개 이상, 최대 5개까지만 지정해야 합니다.",
        min_length=1,
        max_length=5,
    )
    strategy_details: dict[str, Any] = Field(
        description="자유롭게 창조하는 구체적인 매매 전략 데이터. 장세(trend), 리스크 수준(risk), 진입 조건, 기타 하위 에이전트(Meerkat)가 목표가를 설정하는 데 필요한 모든 디테일을 상황에 맞는 JSON 구조(Key-Value)로 마음대로 설계해서 담아."
    )

    @field_validator("target_coins")
    @classmethod
    def format_upbit_tickers(cls, coins: list[str]) -> list[str]:
        formatted_coins = []
        for coin in coins:
            clean_coin = coin.upper().strip()

            if not clean_coin.startswith("KRW-"):
                clean_coin = f"KRW-{clean_coin}"

            formatted_coins.append(clean_coin)

        return formatted_coins
