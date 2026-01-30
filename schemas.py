
# --- Pydantic Schemas ---


from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from typing import Any, Optional,List, Dict
from datetime import datetime, date
from enum import Enum

# Profile Schemas
class ProfileBase(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    phone_number: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


    # --- NEW CONTEST PREFERENCE FIELDS ---
    city_preference: Optional[str] = None
    voluntary_consent: Optional[bool] = None
    fee_consent: Optional[bool] = None

    


class Profile(ProfileBase):
    id: UUID
    account_status: str
    updated_at: datetime
    class Config: from_attributes = True

# Product Schemas
class Product(BaseModel):
    product_id: int
    base_product_id: Optional[int] = None
    product_name: str
    description: Optional[str] = None

    price: float
    mrp: Optional[float] = None
    stock_quantity: int
    unit: Optional[str] = None


    supplier_id: Optional[str] = None
    supplier_product_id: Optional[str] = None

    segment: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    category_group: Optional[str] = None
    category_imgs: Optional[str] = None

    brand_name: Optional[str] = None
    supplier_mrp: Optional[float] = None
    supplier_price_to_qdio: Optional[float] = None

    is_active: bool
    created_at: datetime
    updated_at: datetime


    # CHANGED: These are now Lists of Strings
    
    color: Optional[str] = None
    

    # FIX IS HERE: Changed from List[str] to Dict
    images: Optional[List[str]] = None


       # --- NEW CLOTHING DETAIL FIELDS ---
    Design: Optional[str] = None
    Fit: Optional[str] = None
    Neck: Optional[str] = None
    Sleeve_type: Optional[str] = None
    Wash_care: Optional[str] = None
    Product_description: Optional[str] = None

    class Config: from_attributes = True



# UPDATED: Product Update Schema
class ProductUpdate(BaseModel):
    sizes: Optional[List[str]] = None
    color: Optional[str] = None
    #images: Optional[List[str]] = None

    # UPDATED: Allow updating the complex image structure
    images: Optional[List[str]] = None

     # NEW
    Design: Optional[str] = None
    Fit: Optional[str] = None
    Neck: Optional[str] = None
    Sleeve_type: Optional[str] = None
    Wash_care: Optional[str] = None
    Product_description: Optional[str] = None





# --- NEW: Simple Product schema for nested response ---
# Must be defined BEFORE OrderItem
class ProductSimple(BaseModel):
    product_name: str
    category: Optional[str] = None
    sub_category: Optional[str] = None
    images: Optional[List[str]] = None
    class Config: from_attributes = True

# Delivery Partner Schemas
class DeliveryPartner(BaseModel):
    delivery_partner_id: int
    partner_name: str
    contact_number: Optional[str] = None
    status: str
    class Config: from_attributes = True

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
    brand_discount: float | None = 0
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

# NEW: Payment Verification Schema
class PaymentVerificationRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
    order_id: int

# Auth Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    phone_number: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str


# NEW: Forgot Password Schemas
class UserForgotPassword(BaseModel):
    email: EmailStr

class UserResetPassword(BaseModel):
    new_password: str

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    created_at: datetime
    token: Optional[str] = None




# UPDATED: Added refresh_token field
class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str 



class Supplier(BaseModel):
    supplier_id: str
    key_person_name: Optional[str] = None
    brand_names: Optional[str] = None

    phone_number: Optional[str] = None
    email: Optional[str] = None
    gstin: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    location_link: Optional[str] = None

    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None

    
    brand_tags: Optional[List[str]] = None
    tag_imgs: Optional[List[str]] = None
    brand_store_images: Optional[Dict[str, Any]] = {"slider": [], "offer": None}
    brand_logo: Optional[str] = None
    video_urls: Optional[Dict[str, Optional[str]]] = {
    "brand_story": None,
    "product_detail": None
    }
    brand_intro: Optional[str] = None  
    brand_highlights: Optional[List[Dict[str, Any]]] = []

    
    is_active: Optional[bool] = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True




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




class PartnerCreate(BaseModel):
    full_name: str
    phone_number: str
    email_id: EmailStr
    city_location: Optional[str] = None

    primary_roles: Optional[List[str]] = None
    languages_used: Optional[List[str]] = None
    community_types: Optional[List[str]] = None

    total_community_count: Optional[int] = None

    whatsapp_group_links: Optional[List[str]] = None
    telegram_links: Optional[List[str]] = None
    instagram_profile_links: Optional[List[str]] = None
    facebook_links: Optional[List[str]] = None
    youtube_channel_links: Optional[List[str]] = None

    creates_content: Optional[bool] = None
    content_types: Optional[List[str]] = None

    primary_platforms: Optional[List[str]] = None
    audience_gender: Optional[str] = None
    audience_age_groups: Optional[List[str]] = None

    deal_sharing_experience: Optional[bool] = None
    preferred_product_price_range: Optional[str] = None
    styles_willing_to_promote: Optional[List[str]] = None

    promote_group_deals: Optional[bool] = None
    expected_monthly_earnings: Optional[int] = None
    other_income_sources: Optional[List[str]] = None


class PartnerResponse(PartnerCreate):
    partner_id: UUID
    created_at: datetime


class CouponGenerateRequest(BaseModel):
    brand_code: Optional[str] = None

class CouponGenerateResponse(BaseModel):
    coupon_code: str
    brand_name: str
    brand_code: str
    offer_name: str
    discount_type: str
    discount_value: float
    used_count: int


class CartItem(BaseModel):
    variant_id: int

class CouponValidateRequest(BaseModel):
    coupon_code: str
    cart_items: List[CartItem]

class CouponValidateResponse(BaseModel):
    valid: bool
    coupon_id: Optional[str]= None
    partner_id: Optional[str]= None
    message: str




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
    quantity: int
    return_type: ReturnTypeEnum
    reason: str
    pickup_address: str
    status: ReturnStatusEnum
    initiated_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True

    

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