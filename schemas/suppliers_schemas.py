from pydantic import BaseModel
from typing import Any, Literal, Optional,List, Dict
from datetime import datetime
from pydantic import BaseModel





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


