
from pydantic import BaseModel, EmailStr, Field, model_validator
from uuid import UUID
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel



# Auth Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    partner_code: Optional[str] = None


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
    is_partner: Optional[bool] = False
    partner_id: Optional[UUID] = None


    # --- NEW CONTEST PREFERENCE FIELDS ---
    city_preference: Optional[str] = None
    voluntary_consent: Optional[bool] = None
    fee_consent: Optional[bool] = None

    


class Profile(ProfileBase):
    id: UUID
    account_status: str
    updated_at: datetime
    class Config: from_attributes = True
