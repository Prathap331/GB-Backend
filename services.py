# services.py
import os
import razorpay
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from schemas import UserResponse
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# -------- SUPABASE --------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not SUPABASE_ANON_KEY:
    raise Exception("Supabase env variables missing")

# Admin DB client (server only)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Auth-safe client (for user tokens)
supabase_anon = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# -------- RAZORPAY --------
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise Exception("Razorpay keys missing")

razorpay_client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
    timeout=10
)



oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserResponse:
    try:
        user = supabase_anon.auth.get_user(token).user
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return UserResponse(
            id=user.id,
            email=user.email,
            created_at=user.created_at
        )

    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# -------- SUPPLIER API --------
SUPPLIER_API_URL = os.environ.get("SUPPLIER_API_URL")
SUPPLIER_API_KEY = os.environ.get("SUPPLIER_API_KEY")
SYNC_SECRET = os.environ.get("SYNC_SECRET")


# Fetch products from supplier API
def fetch_supplier_products():
    import requests
    
    if not SUPPLIER_API_URL or not SUPPLIER_API_KEY:
        raise Exception("Supplier API env variables missing")

    headers = {"Authorization": f"Bearer {SUPPLIER_API_KEY}"}

    # res = requests.get(f"{SUPPLIER_API_URL}/products", headers=headers, timeout=15)
    res = requests.get("https://fakestoreapi.com/products", timeout=15)
    res.raise_for_status()

    return res.json()
