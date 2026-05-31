import datetime

from pydantic import BaseModel, Field

from bat_daemon.constant import SignalType
from magpie_agent.agents.meerkat_scanner.schema import TargetSchema
from magpie_agent.agents.owl_director.schema import StrategySchema


class BASE(BaseModel):
    user_id: str
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))


class StrategyEntity(StrategySchema, BASE): ...


class TargetEntity(TargetSchema, BASE): ...


class AssetEntity(BaseModel):
    volume: float = Field(ge=0.0, description="보유 수량")
    avg_buy_price: float = Field(ge=0.0, description="매수 평균가")


class WalletTradeSnapshot(BaseModel):
    market: str | None = Field(default=None, description="가장 최근 체결 코인")
    signal: SignalType | None = Field(default=None, description="가장 최근 체결 방향")
    price: float | None = Field(default=None, ge=0.0, description="가장 최근 체결가")
    volume: float | None = Field(default=None, ge=0.0, description="가장 최근 체결 수량")
    total_price: float | None = Field(default=None, ge=0.0, description="가장 최근 체결 총액")
    executed_at: datetime.datetime | None = Field(default=None, description="가장 최근 체결 시각")


class WalletTradeStats(BaseModel):
    total_buy_krw: float = Field(default=0.0, ge=0.0, description="누적 매수 금액")
    total_sell_krw: float = Field(default=0.0, ge=0.0, description="누적 매도 금액")
    buy_count: int = Field(default=0, ge=0, description="누적 매수 횟수")
    sell_count: int = Field(default=0, ge=0, description="누적 매도 횟수")
    last_trade: WalletTradeSnapshot = Field(default_factory=WalletTradeSnapshot)


class WalletEntity(BASE):
    balance: float = Field(ge=0.0, description="보유 원화")
    assets: dict[str, AssetEntity | None] = Field(default_factory=dict)
    trade_stats: WalletTradeStats = Field(default_factory=WalletTradeStats)


class TradeHistoryEntity(BASE):
    market: str
    signal: SignalType
    price: float = Field(ge=0.0, description="체결가")
    volume: float = Field(ge=0.0, description="체결 수량")
    total_price: float = Field(ge=0.0)
