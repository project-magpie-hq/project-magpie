import datetime

from pydantic import BaseModel, Field

from agents.meerkat_scanner.schema import TargetSchema
from agents.owl_director.schema import StrategySchema


class BASE(BaseModel):
    user_id: str
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))


class StrategyEntity(StrategySchema, BASE): ...


class TargetEntity(TargetSchema, BASE): ...
