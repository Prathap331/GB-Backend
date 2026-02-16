


from pydantic import BaseModel, EmailStr, Field, model_validator
from uuid import UUID
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime, date
from enum import Enum
from pydantic import BaseModel


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
