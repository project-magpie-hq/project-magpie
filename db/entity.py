import datetime

from pydantic import BaseModel, Field
from typing import Literal

from agents.meerkat_scanner.schema import TargetSchema
from agents.owl_director.schema import StrategySchema


class BASE(BaseModel):
    user_id: str
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))


class StrategyEntity(StrategySchema, BASE): ...


class TargetEntity(TargetSchema, BASE): ...


class AssetEntity(BaseModel):
    volume: float = Field(ge=0.0, description="보유 수량")
    avg_buy_price: float = Field(ge=0.0, description="매수 평균가")


class WalletEntity(BASE):
    balance: float = Field(ge=0.0, description="보유 원화")
    assets: dict[str, AssetEntity] = Field(default_factory=dict)


class TradeHistoryEntity(BASE):
    market: str
    type: Literal["buy", "sell"]
    price: float = Field(ge=0.0, description="체결가")
    volume: float = Field(ge=0.0, description="체결 수량")
    total_price: float = Field(ge=0.0)
