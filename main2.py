import os
import razorpay
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from supabase import create_client, Client
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field



# Load environment variables
load_dotenv()

# --- Configuration & Supabase Client ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") # Use the SERVICE_ROLE key

if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Supabase URL and Key must be set in .env file")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Razorpay Configuration ---
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise Exception("Razorpay Key ID and Secret must be set in .env file")

# Initialize Razorpay client
razorpay_client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
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

class Profile(ProfileBase):
    id: UUID
    account_status: str
    updated_at: datetime
    class Config: from_attributes = True

# Product Schemas
class Product(BaseModel):
    product_id: int
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

class OrderItem(BaseModel):
    order_item_id: int
    order_id: int
    product_id: int
    quantity: int
    price_per_unit: float
    subtotal: float
    class Config: from_attributes = True

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    payment_method: str # 'COD', 'Online', 'Wallet'

# UPDATED: Order Response with Razorpay fields
class Order(BaseModel):
    order_id: int
    user_id: UUID
    order_date: datetime
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

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str

# --- Authentication ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserResponse:
    try:
        user_data = supabase.auth.get_user(token)
        user = user_data.user
        if not user: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return UserResponse(id=user.id, email=user.email, created_at=user.created_at)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid credentials: {e}", headers={"WWW-Authenticate": "Bearer"})

# --- API Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Welcome to the E-Commerce API v3 (Razorpay)"}

# --- Auth Endpoints ---

@app.post("/auth/signup", response_model=UserResponse)
async def signup(user: UserCreate):
    try:
        res = supabase.auth.sign_up({"email": user.email, "password": user.password, "options": {"data": {"full_name": user.full_name, "phone": user.phone_number}}})
        if res.user: return UserResponse(id=res.user.id, email=res.user.email, created_at=res.user.created_at)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create user")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@app.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        res = supabase.auth.sign_in_with_password({"email": form_data.username, "password": form_data.password})
        return Token(access_token=res.session.access_token, token_type="bearer")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")

@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user

# --- Profile Endpoints ---

@app.get("/profiles/me", response_model=Profile)
async def get_my_profile(current_user: UserResponse = Depends(get_current_user)):
    try:
        res = supabase.table("profiles").select("*").eq("id", str(current_user.id)).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

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
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@app.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: int):
    try:
        res = supabase.table("products").select("*").eq("product_id", product_id).eq("is_active", True).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or not active")
        return res.data
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
        profile_res = supabase.table("profiles").select("*").eq("id", str(current_user.id)).execute()
        if not profile_res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")
        profile = profile_res.data[0]
        if not all([profile.get("full_name"), profile.get("address_line1"), profile.get("city"), profile.get("postal_code")]):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please complete your profile (full_name, address_line1, city, postal_code) before ordering.")
        delivery_address = f"{profile['full_name']}\n{profile['address_line1']}\n{profile.get('address_line2', '')}\n{profile['city']}, {profile['state']} {profile['postal_code']}\n{profile['country']}"
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
            order_items_to_create.append({"product_id": item.product_id, "quantity": item.quantity, "price_per_unit": price_per_unit, "subtotal": subtotal})
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error validating products: {e}")

    # 4. Create the 'orders' entry in our DB
    razorpay_order_id = None

    contest_id = uuid.uuid4().hex
    try:
        order_data = {
            "user_id": str(current_user.id),
            "total_amount": total_amount,
            "payment_method": order.payment_method,
            "delivery_address": delivery_address,
            "payment_status": "Pending",
            "order_status": "Pending",
            "contest_id": contest_id # Save to DB
        }
        order_res = supabase.table("orders").insert(order_data).execute()
        if not order_res.data: raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create order record")
        new_order = order_res.data[0]
        new_order_id = new_order["order_id"]
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
                "amount": int(total_amount * 100), 
                "currency": "INR",
                "receipt": f"order_rcptid_{new_order_id}",
                "notes": {
                    "internal_order_id": new_order_id,
                    "user_id": str(current_user.id),
                    "contest_id": contest_id # Save to DB
                }
            }
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

    # 7. Return response
    final_order = Order.model_validate(new_order)
    final_order.items = [OrderItem.model_validate(item) for item in new_items]
    
    if razorpay_order_id:
        final_order.razorpay_order_id = razorpay_order_id
        final_order.razorpay_key_id = RAZORPAY_KEY_ID # Send public key

    return final_order

@app.get("/orders/me", response_model=List[Order])
async def get_my_orders(current_user: UserResponse = Depends(get_current_user)):
    try:
        res = supabase.table("orders").select("*, order_items(*)").eq("user_id", str(current_user.id)).order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@app.get("/orders/me/{order_id}", response_model=Order)
async def get_my_single_order(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    try:
        res = supabase.table("orders").select("*, order_items(*)").eq("user_id", str(current_user.id)).eq("order_id", order_id).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

# --- NEW: PAYMENT VERIFICATION ENDPOINT ---

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