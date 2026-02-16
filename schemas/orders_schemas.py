
from pydantic import BaseModel, EmailStr, Field, model_validator
from uuid import UUID
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel

from schemas.product_schemas import ProductSimple



# Order Schemas
class OrderItemCreate(BaseModel):
    variant_id: Optional[int] = None
    quantity: int

    # legacy fields kept (ignored later)
    product_id: Optional[int] = None
    size: Optional[str] = None
    color: Optional[str] = None

    opt_out_delivery: bool = False

class OrderItem(BaseModel):
    order_item_id: int
    order_id: int

    product_id: int
    variant_id: Optional[int] = None


    quantity: int
    price_per_unit: float
    subtotal: float

    supplier_id: Optional[str] = None
    supplier_product_id: Optional[str] = None


    size: Optional[str] = None 
    color: Optional[str] = None 
     
    # UPDATED: Nested product info
    products: Optional[ProductSimple] = None 
    class Config: from_attributes = True

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    payment_method: str # 'COD', 'Online', 'Wallet'
    opt_out_delivery: Optional[bool] = False
    coupon_code: Optional[str] = None

# Add this near your other schemas (like OrderCreate)
class OrderUpdate(BaseModel):
    opt_out_delivery: Optional[bool] = False

# UPDATED: Order Response with Razorpay fields
class Order(BaseModel):
    order_id: int
    user_id: UUID
    order_date: datetime
    shipping_fee: float | None = None
    cod_fee: float | None = None
    gst_amount: float | None = None
    total_amount: float

    coupon_discount: float | None = 0
    total_discount: float | None = 0

    payment_method: str
    payment_status: str
    order_status: str
    delivery_date: Optional[datetime] = None
    return_valid_till: Optional[datetime] = None
    delivery_partner_id: Optional[int] = None
    delivery_address: str
    delivery_expected_date: Optional[datetime] = None
    created_at: datetime
    items: List[OrderItem] = Field(default=[], validation_alias="order_items")
    #items: List[OrderItem] = []

    # New fields for Razorpay
    razorpay_order_id: Optional[str] = None
    razorpay_key_id: Optional[str] = None 

    # NEW: Contest ID Field
    contest_id: Optional[str] = None


    lucky_number: Optional[List[str]] = None # NEW: Lucky Number field
     # NEW: Return this in the response
    opt_out_delivery: bool

    class Config:
        from_attributes = True
