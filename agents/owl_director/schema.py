from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class AgentEnum(StrEnum):
    MEERKAT = "meerkat_scanner"
    END = "END"


class RouterToolInput(BaseModel):
    """다음 작업을 수행할 에이전트를 호출합니다."""

    next_agent: AgentEnum = Field(description="호출할 다음 에이전트의 이름")
