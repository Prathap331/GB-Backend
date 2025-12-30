import os
import io
import json
import uuid
import time
import random

from datetime import datetime, date, timezone
from typing import List, Optional, Dict

import razorpay
from dotenv import load_dotenv
from supabase import create_client, Client

from fastapi import FastAPI, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, EmailStr, Field
from uuid import UUID

# PDF Generator
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors

# Load environment variables
load_dotenv()

# --- Configuration & Supabase Client ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
# SUPABASE_KEY = os.environ.get("SUPABASE_KEY") # Use the SERVICE_ROLE key

SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not SUPABASE_ANON_KEY:
    raise Exception("Supabase URL and Key must be set in .env file")

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)


# --- Razorpay Configuration ---
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise Exception("Razorpay Key ID and Secret must be set in .env file")

# Initialize Razorpay client
razorpay_client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
    timeout=10
)

app = FastAPI(title="E-Commerce Backend v3 (Razorpay)")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas ---

# Profile Schemas
class ProfileBase(BaseModel):
    full_name: Optional[str] = None
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
    category: Optional[str] = None
    description: Optional[str] = None
    price: float
    mrp: Optional[float] = None
    stock_quantity: int
    unit: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime



    # Product Variants
    #size: Optional[str] = None
    #color: Optional[str] = None # NEW: Color Field

    # CHANGED: These are now Lists of Strings
    sizes: Optional[List[str]] = Field(default_factory=list)
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
    image_url: Optional[str] = None
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
    product_id: int
    quantity: int
    # NEW: Allow frontend to send this

    size: Optional[str] = None 
    color: Optional[str] = None # NEW: User selects color
    opt_out_delivery: bool = False

class OrderItem(BaseModel):
    order_item_id: int
    order_id: int
    product_id: int
    quantity: int
    price_per_unit: float
    subtotal: float

    size: Optional[str] = None 
    color: Optional[str] = None # NEW: Saved color


     
    # UPDATED: Nested product info
    products: Optional[ProductSimple] = None 
    class Config: from_attributes = True

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    payment_method: str # 'COD', 'Online', 'Wallet'
    opt_out_delivery: bool = False

# Add this near your other schemas (like OrderCreate)
class OrderUpdate(BaseModel):
    opt_out_delivery: bool

# UPDATED: Order Response with Razorpay fields
class Order(BaseModel):
    order_id: int
    user_id: UUID
    order_date: datetime
    shipping_fee: float | None = None
    cod_fee: float | None = None
    gst_amount: float | None = None
    total_amount: float
    payment_method: str
    payment_status: str
    order_status: str
    delivery_partner_id: Optional[int] = None
    delivery_address: str
    delivery_expected_date: Optional[date] = None
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




# UPDATED: Added refresh_token field
class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str 



def calculate_order_pricing(order, db_products):
    total_amount = 0.0

    # subtotal
    for item in order.items:
        product = db_products[item.product_id]
        total_amount += float(product["price"]) * item.quantity

    # discount (based on quantity)
    total_items = sum(item.quantity for item in order.items)
    discount_rate = 0.4 if total_items >= 5 else 0.3 if total_items >= 3 else 0
    discount_amount = round(total_amount * discount_rate, 2)

    discounted = round(total_amount - discount_amount, 2)

    # GST (5% after discount)
    gst_amount = round(discounted * 0.05, 2)
    final = round(discounted + gst_amount, 2)

    # shipping (below 499)
    shipping = 49.0 if final < 499 else 0.0
    grand = round(final + shipping, 2)

    # COD
    cod_fee = 0.0
    if order.payment_method == "COD":
        cod_fee = round(grand * 0.02, 2)
        if cod_fee < 40:
            cod_fee = 40.0
        grand = round(grand + cod_fee, 2)

    return {
        "subtotal": round(total_amount, 2),
        "discount": discount_amount,
        "gst": gst_amount,
        "shipping_fee": shipping,
        "cod_fee": cod_fee,
        "total": grand,
        "discount_rate": discount_rate
    }



def generate_pdf_invoice(order_data, user_data, items_data):
    """
    Generates a PDF invoice in memory and returns the bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # --- Header ---
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, height - 50, "Qdio")
    
    c.setFont("Helvetica", 12)
    c.drawRightString(width - 50, height - 50, "TAX INVOICE")

    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, "Flat no. 502, Meenakshi enclave MIG 891 KPHB phase 3")
    c.drawString(50, height - 85, "Kukatpally, Hyderabad, 500072")
    c.drawString(50, height - 100, "GSTIN: 36AAQCM4860P1ZK")
    c.drawString(50, height - 115, "Contact: support@qdio.shop")
    c.drawString(50, height - 130, "Registered Company: Morpho Technologies Pvt Ltd")

    c.line(50, height - 148, width - 50, height - 148)

    # --- Invoice Details ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, height - 170, f"Invoice #: INV-{order_data['order_id']}")
    
    try:
        dt = datetime.fromisoformat(order_data['created_at'].replace('Z', '+00:00'))
        date_str = dt.strftime("%d %b %Y")
    except:
        date_str = str(datetime.now().date())
        
    c.drawString(300, height - 170, f"Invoice Date: {date_str}")
    c.drawString(50, height - 185, f"Order ID: {order_data.get('razorpay_order_id') or 'N/A'}")

    # --- Bill To / Ship To ---
    y = height - 200
    c.drawString(50, y, "Bill To / Ship To:")
    c.setFont("Helvetica", 10)
    y -= 15
    c.drawString(50, y, user_data.get('full_name') or "Customer")
    y -= 15
    
    address_lines = user_data.get('address_line1', '').split('\n')
    for line in address_lines:
        c.drawString(50, y, line)
        y -= 12
    
    c.drawString(50, y, f"{user_data.get('city', '')}, {user_data.get('state', '')} - {user_data.get('postal_code', '')}")
    y -= 15
    c.drawString(50, y, f"Phone: {user_data.get('phone_number', '')}")

    # --- Items Table Header ---
    y = height - 300
    c.line(50, y, width - 50, y)
    y -= 15
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Item")
    c.drawString(300, y, "Rate")
    c.drawString(380, y, "Qty")
    c.drawString(450, y, "Total")
    y -= 10
    c.line(50, y, width - 50, y)

    # --- Items Rows ---
    c.setFont("Helvetica", 10)
    y -= 20
    
    for item in items_data:
        product = item.get("products") or {}

        name = (
            item.get("product_name")
            or product.get("product_name")
            or "Unknown Item"
        )

        category = (
            item.get("category")
            or product.get("category")
            or ""
        )

        display_name = f"{name} {category}".strip()

        price = item.get("price_per_unit") or item.get("price") or 0
        qty = item.get("quantity") or 1
        subtotal = item.get("subtotal") or (price * qty)


        c.drawString(50, y, display_name[:45]) 
        c.drawString(300, y, f"Rs. {price}")
        c.drawString(380, y, str(qty))
        c.drawString(450, y, f"Rs. {subtotal}")
        y -= 20

    c.line(50, y, width - 50, y)

    # --- Totals ---
    grand_total = float(order_data['total_amount'])
    tax_rate = 0.05
# Base amount (without GST)
    base_amount = grand_total / (1 + tax_rate)
# GST amount
    tax_amount = grand_total - base_amount
    # total_amount = grand_total
    y -= 10
    c.setFont("Helvetica", 10)
    
    c.drawRightString(width - 50, y, f"Subtotal: Rs. {base_amount:.2f}")
    y -= 15
    c.drawRightString(width - 50, y, f"CGST/SGST (5%): Rs. {tax_amount:.2f}")
    y -= 20 
    
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(width - 50, y, f"Grand Total: Rs. {grand_total:.2f}")
    
    # --- Notes Section ---
    y -= 40
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Notes:")
    
    c.setFont("Helvetica", 10)
    # y -= 15
    # contest_id = order_data.get('contest_id', 'Not Assigned')
    # c.drawString(50, y, f"Contest ID: {contest_id}")
    y -= 15
    
    # --- NEW: Lucky Number ---
    lucky_numbers = order_data.get('lucky_number', 'Not Assigned')
    if isinstance(lucky_numbers, list):
        for ln in lucky_numbers:
            c.drawString(50, y, f"Lucky Number: {ln}")
            y -= 15
    else:
        c.drawString(50, y, f"Lucky Number: {lucky_numbers}")
        y -= 15
    c.drawString(50, y, "Keep these numbers safe for future rewards!")

    # --- Terms and Conditions ---
    y -= 40
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Terms & Conditions:")
    
    c.setFont("Helvetica", 9)
    y -= 15
    c.drawString(50, y, "1. Your contest lucky number becomes invalid if you return the product.")
    y -= 12
    c.drawString(50, y, "2. All disputes are subject to Hyderabad jurisdiction only.")

    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(width / 2, 50, "Thank you for shopping with Qdio!")
    c.drawCentredString(width / 2, 35, "This is a computer generated invoice.")

    c.save()
    buffer.seek(0)
    return buffer.read()




# --- Authentication ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserResponse:
    try:
        user_client = create_client(
            SUPABASE_URL,
            SUPABASE_ANON_KEY
        )

        user = user_client.auth.get_user(token).user
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return UserResponse(
            id=user.id,
            email=user.email,
            created_at=user.created_at
        )

    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# --- API Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Welcome to the E-Commerce API v3 (Razorpay)"}

# --- Auth Endpoints ---
'''
@app.post("/auth/signup", response_model=UserResponse)
async def signup(user: UserCreate):
    try:
        res = supabase.auth.sign_up({"email": user.email, "password": user.password, "options": {"data": {"full_name": user.full_name, "phone": user.phone_number}}})
        if res.user: return UserResponse(id=res.user.id, email=res.user.email, created_at=res.user.created_at)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create user")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
'''

@app.post("/auth/signup", response_model=UserResponse)
async def signup(user: UserCreate):
    try:
        res = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password,
            "options": {
                "data": {
                    "full_name": user.full_name,
                    "phone": user.phone_number
                }
            }
        })
        
        if res.user:
            # --- THE "SHERLOCK HOLMES" CHECK ---
            
            # 1. Check if this user ID actually made it into our 'profiles' table.
            # If the email was a duplicate, Supabase sends a FAKE user with a random ID 
            # that will NOT exist in our database.
            profile_check = supabase.table("profiles").select("id").eq("id", res.user.id).execute()
            
            # If the list is empty, it was a fake success (Duplicate Email)
            if not profile_check.data:
                 raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, 
                    detail="Account already exists. Please login instead."
                )

            # 2. (Backup Check) If it IS a real user object but from the past 
            # (in case settings change later), check the timestamp.
            user_created_at = res.user.created_at
            
            # Handle both string and datetime formats safely
            if isinstance(user_created_at, str):
                user_created_at = datetime.fromisoformat(user_created_at.replace("Z", "+00:00"))
            
            # Ensure timezone awareness
            if user_created_at.tzinfo is None:
                user_created_at = user_created_at.replace(tzinfo=timezone.utc)
                
            now = datetime.now(timezone.utc)
            if (now - user_created_at).total_seconds() > 30:
                 raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, 
                    detail="Account already exists. Please login instead."
                )

            return UserResponse(
                id=res.user.id,
                email=res.user.email,
                created_at=res.user.created_at
            )
            
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create user")

    except Exception as e:
        if isinstance(e, HTTPException): raise e
        
        error_msg = str(e)
        if "User already registered" in error_msg or "already exists" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="Account already exists. Please login instead."
            )
            
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    


# UPDATED: Login endpoint now returns refresh_token
@app.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        res = supabase.auth.sign_in_with_password({
            "email": form_data.username, 
            "password": form_data.password
        })
        return Token(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token, # Extracting refresh token
            token_type="bearer"
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")





@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user





# --- NEW: Forgot Password Endpoints ---

@app.post("/auth/forgot-password")
async def forgot_password(data: UserForgotPassword):
    """
    Trigger a password reset email via Supabase.
    Handles rate limiting errors gracefully.
    """
    try:
        # UPDATE: Set the redirect URL explicitly.
        # Change this URL to your actual frontend reset page.
        # Example for local testing: "http://localhost:3000/reset-password"
        # Example for production: "https://goldenbanana.vercel.app/reset-password"  
        redirect_url = "https://www.qdio.shop/reset-password" 
        
        supabase.auth.reset_password_email(data.email, options={"redirectTo": redirect_url})
    

       

        return {"message": "Password reset email sent if account exists"}
        
    except Exception as e:
        error_msg = str(e)
        
        # Check for Rate Limit or Server errors from Supabase email service
        if "556" in error_msg or "429" in error_msg:
             raise HTTPException(
                 status_code=status.HTTP_429_TOO_MANY_REQUESTS, 
                 detail="Too many email requests. Please wait a few minutes before trying again."
             )
             
        # For security, we generally don't want to tell the user if the email failed 
        # (unless it's a rate limit), so we often return success or a generic error.
        # But for dev debugging, we return the detail.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Email service error: {error_msg}")




'''
@app.post("/auth/reset-password")
async def reset_password(
    data: UserResetPassword, 
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Update the password for the logged-in user.
    This endpoint requires the Bearer Token obtained from the password reset email link.
    """
    try:
        attributes = {"password": data.new_password}
        supabase.auth.update_user(attributes)
        return {"message": "Password updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


'''
@app.post("/auth/reset-password")
async def reset_password(
    data: UserResetPassword,
    token: str = Depends(oauth2_scheme)
):
    try:
        user_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

        # Attach the token to this client session
        user_client.auth.set_session(
            access_token=token,
            refresh_token=""
        )

        user_client.auth.update_user({"password": data.new_password})
        return {"message": "Password updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))





# --- Profile Endpoints ---
@app.get("/profiles/me", response_model=Profile)
async def get_my_profile(current_user: UserResponse = Depends(get_current_user)):
    try:
        res = (
            supabase.table("profiles")
            .select("*")
            .eq("id", str(current_user.id))
            .maybe_single()
            .execute()
        )

        # --- AUTO CREATE PROFILE FOR GOOGLE USERS ---
        if not res.data:
            profile = {
                "id": str(current_user.id),
                "full_name": current_user.email.split("@")[0],
                "account_status": "active",
                "updated_at": datetime.utcnow().isoformat(),
            }

            insert_res = supabase.table("profiles").insert(profile).execute()
            return insert_res.data[0]
        # -------------------------------------------

        return res.data

    except HTTPException:
        raise  

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )




@app.put("/profiles/me", response_model=Profile)
async def update_my_profile(profile: ProfileBase, current_user: UserResponse = Depends(get_current_user)):
    try:
        update_data = profile.model_dump(exclude_unset=True)
        if not update_data: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")
        update_data["updated_at"] = datetime.now().isoformat()
        res = supabase.table("profiles").update(update_data).eq("id", str(current_user.id)).execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found or update failed")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

# --- Product Endpoints ---

@app.get("/products", response_model=List[Product])
async def get_products():
    try:
        res = supabase.table("products").select("*").order("created_at", desc=True).execute()
        products = res.data

        # Convert images from string to list safely
        for p in products:
            if isinstance(p.get("images"), str):
                try:
                    p["images"] = json.loads(p["images"])
                except:
                    p["images"] = []  # fallback

        return products

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: int):
    try:
        res = supabase.table("products").select("*").eq("product_id", product_id).single().execute()
        product = res.data
        if not product:
            raise HTTPException(404, "Product not found")

        # Convert images string → list
        if isinstance(product.get("images"), str):
            try:
                product["images"] = json.loads(product["images"])
            except:
                product["images"] = []

        return product

    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/products/base/{base_product_id}", response_model=List[Product])
async def get_products_by_base_id(base_product_id: int):
    try:
        res = (
            supabase.table("products")
            .select("*")
            .eq("base_product_id", base_product_id)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )

        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No variants found for this base product"
            )

        return res.data

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )






'''
# --- Update Product (Size & Color) Endpoint ---
@app.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int, 
    product_update: ProductUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        update_data = product_update.model_dump(exclude_unset=True)
        if not update_data:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

        update_data["updated_at"] = datetime.now().isoformat()
        res = supabase.table("products").update(update_data).eq("product_id", product_id).execute()
        if not res.data or len(res.data) == 0:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or update failed")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

'''










# --- Updated Product Update (Handles Arrays) ---
@app.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int, 
    product_update: ProductUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        update_data = product_update.model_dump(exclude_unset=True)
        if not update_data:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

        update_data["updated_at"] = datetime.now().isoformat()
        res = supabase.table("products").update(update_data).eq("product_id", product_id).execute()
        if not res.data or len(res.data) == 0:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or update failed")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))













# --- Delivery Partner Endpoints ---

@app.get("/delivery-partners", response_model=List[DeliveryPartner])
async def get_delivery_partners(current_user: UserResponse = Depends(get_current_user)):
    try:
        res = supabase.table("delivery_partners").select("*").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

#--- lucky number ---
def generate_unique_lucky_numbers(count: int):
    lucky_numbers = []

    existing_numbers = supabase.table("lucky_numbers") \
        .select("lucky_number") \
        .execute().data
    existing_set = {row["lucky_number"] for row in existing_numbers}

    while len(lucky_numbers) < count:
        ln = f"{random.randint(0, 9999999):07d}"
        if ln not in existing_set:
            lucky_numbers.append(ln)
            existing_set.add(ln)

    return lucky_numbers



@app.post("/orders/price-preview")
async def price_preview(order: OrderCreate):

    product_ids = [item.product_id for item in order.items]
    res = supabase.table("products").select(
        "product_id, price"
    ).in_("product_id", product_ids).execute()

    db_products = {p["product_id"]: p for p in res.data}

    pricing = calculate_order_pricing(order, db_products)

    return pricing



# --- Order Endpoints (UPDATED WITH RAZORPAY) ---

@app.post("/orders", response_model=Order)
async def create_order(
    order: OrderCreate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new order. If 'Online', it also creates a Razorpay order.
    """
    
    # 1. Get user's profile to fetch address
    try:
        profile_res = (supabase.table("profiles").select("*").eq("id", str(current_user.id)).maybe_single().execute())
        profile = profile_res.data

        if not profile: 
            profile = {
                "id": str(current_user.id),
                "full_name": None,
                "phone_number": None,
                "address_line1": None,
                "address_line2": None,
                "city": None,
                "state": None,
                "postal_code": None,
                "country": None,
                "city_preference": "",
                "voluntary_consent": False,
                "fee_consent": False,
                "account_status": "active",
                "updated_at": datetime.utcnow().isoformat(),
            }
            supabase.table("profiles").insert(profile).execute()

        required_fields = [
            profile.get("full_name"),
            profile.get("address_line1"),
            profile.get("city"),
            profile.get("postal_code")
        ]

        if any(f in (None, "", " ") for f in required_fields):
            raise HTTPException(
                status_code=400,
                detail="Please complete your profile (name, address, city, postal code) before ordering."
            )

# SAFE ADDRESS FORMAT
        delivery_address = (
            f"{profile.get('full_name','')}\n"
            f"{profile.get('address_line1','')}\n"
            f"{profile.get('address_line2','')}\n"
            f"{profile.get('city','')}, {profile.get('state','')} {profile.get('postal_code','')}\n"
            f"{profile.get('country','')}"
        )    

    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error fetching profile: {e}")

    # 2 & 3. Validate products & calculate total
    total_amount = 0.0
    order_items_to_create = []
    try:
        product_ids = [item.product_id for item in order.items]
        if not product_ids: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No items in order")
        res = supabase.table("products").select("product_id, price, stock_quantity, product_name").in_("product_id", product_ids).execute()
        db_products = {p["product_id"]: p for p in res.data}
        
        for item in order.items:
            product = db_products.get(item.product_id)
            if not product: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {item.product_id} not found")
            if product["stock_quantity"] < item.quantity: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Not enough stock for {product['product_name']}")
            price_per_unit = float(product["price"])
            subtotal = price_per_unit * item.quantity
            total_amount += subtotal
            order_items_to_create.append({"product_id": item.product_id, "quantity": item.quantity, "price_per_unit": price_per_unit, "subtotal": subtotal,
                                          "size": item.size,
                "color": item.color # User selected color
                                          
                                        })

        # ---- USE SHARED PRICING FUNCTION ----
        pricing = calculate_order_pricing(order, db_products)

        grand_total   = pricing["total"]
        gst_amount    = pricing["gst"]
        shipping_fee  = pricing["shipping_fee"]
        cod_fee       = pricing["cod_fee"]
        discount_rate = pricing["discount_rate"]

        print("[PRICE PREVIEW]", pricing)


    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error validating products: {e}")

    # 4. Create the 'orders' entry in our DB
    razorpay_order_id = None
    # --- GENERATE HASH HERE ---
    contest_id = uuid.uuid4().hex

    # NEW: Generate Random 7-digit Lucky Number
    # lucky_number = f"{random.randint(0, 9999999):07d}"
    lucky_count = int(total_amount // 1000)
    lucky_numbers = generate_unique_lucky_numbers(lucky_count)


    
    try:
        order_data = {
            "user_id": str(current_user.id),
            "total_amount": round(grand_total, 2),
            "payment_method": order.payment_method,
            "delivery_address": delivery_address,
            "payment_status": "Pending",
            "order_status": "Pending",
            "contest_id": contest_id ,# Save to DB
            "lucky_number": lucky_numbers, # NEW: Save to DB
            # NEW: Save the opt-out preference
            "opt_out_delivery": order.opt_out_delivery 
        }
        order_res = supabase.table("orders").insert(order_data).execute()
        if not order_res.data: raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create order record")
        new_order = order_res.data[0]
        new_order_id = new_order["order_id"]
        # Save each lucky number to lucky_numbers table
        for ln in lucky_numbers:
            supabase.table("lucky_numbers").insert({
                "order_id": new_order_id,
                "user_id": str(current_user.id),
                "lucky_number": ln
            }).execute()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating order in DB: {e}")

    # 5. Create 'order_items'
    try:
        for item in order_items_to_create:
            item["order_id"] = new_order_id
        items_res = supabase.table("order_items").insert(order_items_to_create).execute()
        new_items = items_res.data
    except Exception as e:
        supabase.table("orders").delete().eq("order_id", new_order_id).execute()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating order items: {e}")

    # --- 6. RAZORPAY LOGIC ---
    if order.payment_method == "Online":
        try:
            # Amount is in paisa (100 paisa = 1 Rupee)
            rzp_order_data = {
                "amount": int(round(order_data["total_amount"] * 100)),
                "currency": "INR",
                "receipt": f"order_rcptid_{new_order_id}",
                "notes": {
                    "internal_order_id": new_order_id,
                    "user_id": str(current_user.id),
                    "contest_id": contest_id, # Save to DB
                    "lucky_number": lucky_numbers, # NEW: Save to DB
                    "opt_out_delivery": str(order.opt_out_delivery)
                }
            }
            print(
                "[RZP DEBUG]",
                f"backend_total={order_data['total_amount']}",
                f"rzp_amount_paise={rzp_order_data['amount']}"
            )

            rzp_order = razorpay_client.order.create(data=rzp_order_data)
            razorpay_order_id = rzp_order["id"]
            
            # Save razorpay_order_id to DB
            supabase.table("orders").update({"razorpay_order_id": razorpay_order_id}).eq("order_id", new_order_id).execute()
            
            # Update local object for response
            new_order["razorpay_order_id"] = razorpay_order_id

        except Exception as e:
            # Cleanup if Razorpay fails
            supabase.table("orders").delete().eq("order_id", new_order_id).execute()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Razorpay creation failed: {e}")




    '''
    # 7. Return response
    final_order = Order.model_validate(new_order)
    final_order.items = [OrderItem.model_validate(item) for item in new_items]
    
    if razorpay_order_id:
        final_order.razorpay_order_id = razorpay_order_id
        final_order.razorpay_key_id = RAZORPAY_KEY_ID # Send public key

    return final_order'''
    # FIX: Fetch the order AGAIN to include nested product details for the response
    # This step was previously returning raw dict, skipping model validation and Razorpay key injection.
    full_order_res = supabase.table("orders").select("*, order_items(*, products(product_name, category, image_url))").eq("order_id", new_order_id).single().execute()
    
    # 1. Convert the DB dictionary to your Pydantic Model
    final_order = Order.model_validate(full_order_res.data)
    
    # 2. Inject Razorpay keys if they exist (since they are env vars, not in DB)
    if razorpay_order_id:
        final_order.razorpay_order_id = razorpay_order_id
        final_order.razorpay_key_id = RAZORPAY_KEY_ID 
    
    final_order.shipping_fee = shipping_fee
    final_order.gst_amount = gst_amount
    final_order.cod_fee = cod_fee

    return final_order
'''
@app.get("/orders/me", response_model=List[Order])
async def get_my_orders(current_user: UserResponse = Depends(get_current_user)):
    try:
        res = supabase.table("orders").select("*, order_items(*)").eq("user_id", str(current_user.id)).order("created_at", desc=True).execute()
        return res.data
    
        
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    '''



@app.get("/orders/me", response_model=List[Order])
async def get_my_orders(current_user: UserResponse = Depends(get_current_user)):
    try:
        # The query string here is critical. We ask for products explicitly.
        res = supabase.table("orders").select("*, order_items(*, products(product_name,category, image_url))").eq("user_id", str(current_user.id)).order("created_at", desc=True).execute()
        
        return [Order.model_validate(o) for o in res.data]
    
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/orders/me/{order_id}", response_model=Order)
async def get_my_single_order(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    try:
        '''
        res = supabase.table("orders").select("*, order_items(*)").eq("user_id", str(current_user.id)).eq("order_id", order_id).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return res.data'''
        # UPDATED QUERY: Fetch nested products(product_name, image_url)
        res = supabase.table("orders").select("*, order_items(*, products(product_name,category, image_url))").eq("user_id", str(current_user.id)).eq("order_id", order_id).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        
       
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

# --- NEW: PAYMENT VERIFICATION ENDPOINT ---


@app.put("/orders/{order_id}", response_model=Order)
async def update_order(
    order_id: int,
    order_update: OrderUpdate,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Update opt_out_delivery.
    """
    try:
        # check order
        existing_res = (
            supabase.table("orders")
            .select("*")
            .eq("order_id", order_id)
            .eq("user_id", str(current_user.id))
            .execute()
        )

        if not existing_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
            )

        # update
        update_data = {"opt_out_delivery": order_update.opt_out_delivery}

        res = (
            supabase.table("orders")
            .update(update_data)
            .eq("order_id", order_id)
            .execute()
        )

        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Update failed",
            )

        # fetch updated
        final_res = (
            supabase.table("orders")
            .select("*, order_items(*, products(product_name,category, image_url))")
            .eq("order_id", order_id)
            .execute()
        )

        if not final_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found after update",
            )

        return final_res.data[0]

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.post("/payment/verify")
async def verify_payment(
    data: PaymentVerificationRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Verify a Razorpay payment signature.
    """
    
    # 1. Check if order exists
    try:
        order_res = supabase.table("orders").select("*").eq("order_id", data.order_id).eq("user_id", str(current_user.id)).single().execute()
        if not order_res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        order = order_res.data
        if order["payment_status"] == "Completed":
            return {"status": "success", "message": "Payment already verified"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error fetching order: {e}")

    # 2. Verify Signature
    try:
        params_dict = {
            'razorpay_order_id': data.razorpay_order_id,
            'razorpay_payment_id': data.razorpay_payment_id,
            'razorpay_signature': data.razorpay_signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Payment verification failed: Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Verification error: {e}")

    # 3. Update DB
    try:
        update_data = {
            "payment_status": "Completed",
            "order_status": "Confirmed",
            "razorpay_payment_id": data.razorpay_payment_id
        }
        supabase.table("orders").update(update_data).eq("order_id", data.order_id).execute()
        
        return {"status": "success", "message": "Payment verified and order confirmed"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"DB update failed: {e}")
    


'''

# --- NEW ENDPOINT: Download Invoice ---
@app.get("/orders/{order_id}/invoice")
async def get_order_invoice(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """
    Generate and download a PDF invoice for a specific order.
    """
    try:
        # 1. Fetch Order details (including Items)
        order_res = supabase.table("orders").select("*, order_items(*, products(*))").eq("order_id", order_id).eq("user_id", str(current_user.id)).execute()
        
        if not order_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        
        order_data = order_res.data[0]
        items_data = order_data.get('order_items', [])

        # 2. Fetch User Profile (for Address)
        user_res = supabase.table("profiles").select("*").eq("id", str(current_user.id)).single().execute()
        user_data = user_res.data or {}

        # 3. Generate PDF
        pdf_bytes = generate_pdf_invoice(order_data, user_data, items_data)

        # 4. Return as downloadable file
        headers = {
            'Content-Disposition': f'attachment; filename="invoice_{order_id}.pdf"'
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

'''

# --- UPDATED ENDPOINT: Download Invoice (With Payment Check) ---
@app.get("/orders/{order_id}/invoice")
async def get_order_invoice(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """
    Generate and download a PDF invoice for a specific order.
    Only allows download if payment_status is 'Completed'.
    """
    try:
        # 1. Fetch Order details
        order_res = supabase.table("orders").select("*, order_items(*, products(product_name, category))").eq("order_id", order_id).eq("user_id", str(current_user.id)).execute()
        
        if not order_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        
        order_data = order_res.data[0]

        # --- NEW SECURITY CHECK ---
        # Prevent generating invoice for unpaid/pending orders
        if order_data.get("payment_status") != "Completed":
             raise HTTPException(
                 status_code=status.HTTP_400_BAD_REQUEST, 
                 detail="Invoice cannot be generated. Payment is not completed."
             )
        # --------------------------

        items_data = order_data.get('order_items', [])

        # 2. Fetch User Profile (for Address)
        user_res = supabase.table("profiles").select("*").eq("id", str(current_user.id)).execute()
        user_data = user_res.data[0] if user_res.data else {}

        # 3. Generate PDF
        pdf_bytes = generate_pdf_invoice(order_data, user_data, items_data)

        # 4. Return as downloadable file
        headers = {
            'Content-Disposition': f'attachment; filename="invoice_{order_id}.pdf"'
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    except Exception as e:
        # If we manually raised the 400 above, allow it to pass through
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
