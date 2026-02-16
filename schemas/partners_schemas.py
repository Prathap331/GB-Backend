
from pydantic import BaseModel, EmailStr, Field, model_validator
from uuid import UUID
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel



class PartnerActivateRequest(BaseModel):
    partner_id: UUID



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
    partner_code: Optional[str] = None
    created_at: datetime



class PartnerSignupRequest(BaseModel):
    partner_id: UUID
    full_name: str
    email: EmailStr
    phone_number: str
    password: str
    confirm_password: str

    @model_validator(mode="after")
    def check_passwords(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class PartnerLoginRequest(BaseModel):
    email: EmailStr
    password: str



class PartnerProfileBase(BaseModel):
    full_name: str
    email: EmailStr
    phone_number: str
    
class PartnerDashboardResponse(BaseModel):
    partner_id: UUID
    partner_name: str

    # --- SALES ---
    total_sale_value: float

    # --- COUPONS ---
    total_coupons: int
    active_coupons_count: int
    active_coupon_codes: list[str]
    total_coupon_usage: int

    # --- ORDERS ---
    total_orders: int
    products_sold: int

    # --- BRANDS ---
    associated_brands: list[str]

    # --- EARNINGS ---
    total_earnings: float = 0.0
