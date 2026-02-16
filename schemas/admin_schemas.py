
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel



# Delivery Partner Schemas
class DeliveryPartner(BaseModel):
    delivery_partner_id: int
    partner_name: str
    contact_number: Optional[str] = None
    status: str
    class Config: from_attributes = True

# NEW: Payment Verification Schema
class PaymentVerificationRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
    order_id: int



# UPDATED: Added refresh_token field
class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str 




class BrandResponse(BaseModel):
    brand_id: UUID
    brand_name: str
    brand_logo: Optional[str] = None
    background_imgs: Optional[List[str]] = None
    brand_discount: Optional[str] = None
    brand_types: Optional[List[str]] = None
    brand_tags: Optional[List[str]] = None

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    category_id: UUID
    segment: str
    category_name: str
    category_imgs: Optional[str] = None
    offer_label: Optional[str] = None




class CartItem(BaseModel):
    variant_id: int
    

class DeliveryStatusEnum(str, Enum):
    ASSIGNED = "Assigned"
    PICKED_UP = "Picked Up"
    OUT_FOR_DELIVERY = "Out for Delivery"
    DELIVERED = "Delivered"
    FAILED = "Failed"
    RETURNED = "Returned"

class DeliveryStatusCreate(BaseModel):
    status: DeliveryStatusEnum
    delivery_partner_id: Optional[int] = None
    remarks: Optional[str] = None



class CouponBase(BaseModel):
    coupon_code: str = Field(..., example="TBH20")

    offer_by: str = Field(..., example="direct")  
    # direct | partner

    offer_scope: str = Field(..., example="brand")
    # universal | brand | product

    discount_type: str = Field(..., example="percentage")
    # percentage | flat

    discount_value: float = Field(..., example=20)

    min_quantity: int = Field(1, example=2)

    start_date: datetime
    end_date: datetime

    is_active: bool = True



class AdminCouponResponse(BaseModel):
    coupon_code: str
    offer_by: str
    offer_scope: str
    discount_type: str
    discount_value: float
    partner_id: Optional[UUID]
    brand_id: Optional[UUID]
    start_date: datetime
    end_date: datetime
    is_active: bool



class AdminCouponCreateRequest(BaseModel):
    
    offer_by: Literal["direct", "partner"]   # who owns it
    offer_scope: Literal["universal", "brand"]

    brand_code: Optional[str] = None         # required if brand
    partner_id: Optional[UUID] = None        # required if partner

    discount_type: Literal["percentage", "flat"]
    discount_value: float
    min_quantity: int = 1

    start_date: datetime
    end_date: datetime
    is_active: bool = True

