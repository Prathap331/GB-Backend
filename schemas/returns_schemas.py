from pydantic import BaseModel, EmailStr, Field, model_validator
from uuid import UUID
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel



class ReturnTypeEnum(str, Enum):
    RETURN = "RETURN"
    EXCHANGE = "EXCHANGE"


class ReturnStatusEnum(str, Enum):
    REQUESTED = "REQUESTED"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    PICKED_UP = "PICKED_UP"
    REFUND_INITIATED = "REFUND_INITIATED"
    REFUNDED = "REFUNDED"
    EXCHANGE_SHIPPED = "EXCHANGE_SHIPPED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"

class ReturnCreate(BaseModel):
    order_id: int
    variant_id: int
    product_id: Optional[int] = None
    quantity: int = 1
    return_type: ReturnTypeEnum
    reason: str
    pickup_address: str

class ReturnUpdate(BaseModel):
    status: ReturnStatusEnum    

class ReturnResponse(BaseModel):
    return_id: int
    order_id: int
    product_id: int
    variant_id: int
    quantity: int
    return_type: ReturnTypeEnum
    reason: str
    pickup_address: str
    status: ReturnStatusEnum
    initiated_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True

