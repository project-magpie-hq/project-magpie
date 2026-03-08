from pydantic import BaseModel, Field


class PriceTargetSchema(BaseModel):
    target_coin: str = Field(description="투자할 타겟 코인 티커 (예: 'KRW-BTC', 'KRW-SOL'). 반드시 업비트 티커 형식으로 작성")
    target_buy_price: float = Field(description="데몬이 매수를 실행할 목표가")
    take_profit_price: float = Field(description="익절 목표가")
    stop_loss_price: float = Field(description="손절 방어선")
    reason: str = Field(description="이 타점을 계산한 근거를 상세하게 50자 이내로 작성")


class MonitoringTargetSchema(BaseModel):
    targets: list[PriceTargetSchema] = Field(description="계산된 각 코인별 타점 리스트")
