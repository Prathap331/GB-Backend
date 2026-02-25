# services.py
from datetime import datetime
import os
import razorpay
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from schemas.auth_schemas import UserResponse
from dotenv import load_dotenv
from supabase import create_client
import boto3

load_dotenv()

# -------- SUPABASE --------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not SUPABASE_ANON_KEY:
    raise Exception("Supabase env variables missing")

SUPABASE_SERVICE_ROLE_KEY = SUPABASE_SERVICE_ROLE_KEY.strip()
SUPABASE_ANON_KEY = SUPABASE_ANON_KEY.strip()



# Admin DB client (server only)
supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Auth-safe client (for user tokens)
supabase_anon = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# Pure DB client (NO auth state, RLS bypass)
supabase_db = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)


def get_user_supabase(token: str):
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(token)
    return client





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
            created_at=user.created_at,
            token=token 
        )

    except Exception as e:
        msg = str(e)

        if "JWT expired" in msg or "PGRST303" in msg:
            raise HTTPException(status_code=401, detail="JWT expired")

        raise HTTPException(status_code=401, detail="Invalid token")



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



ses_client = boto3.client(
    "ses",
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

def send_order_email(
    to_email: str,
    order_id: int,
    total_amount: float,
    items: list
):
    try:
        subject = f"Order Confirmation – #{order_id} | Qdio"

        # Build items table rows
        items_html = ""
        for item in items:
            name = item.get("product_name", "Item")
            qty = item.get("quantity", 1)
            price = item.get("price_per_unit", 0)

            items_html += f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #eee;">
                    {name}
                </td>
                <td style="padding:10px;border-bottom:1px solid #eee;text-align:center;">
                    {qty}
                </td>
                <td style="padding:10px;border-bottom:1px solid #eee;text-align:right;">
                    ₹{price}
                </td>
            </tr>
            """

        body_html = f"""
        <html>
        <body style="font-family:Arial,sans-serif;background:#f6f6f6;padding:20px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto;background:#ffffff;border-radius:8px;overflow:hidden;">
                
                <!-- Header -->
               <tr>
                    <td style="background:#c74242;color:#ffffff;padding:20px;text-align:center;">
                        <h2 style="margin:0;letter-spacing:2px;">QDIO</h2>
                        <p style="margin:5px 0 0;font-size:14px;">Order Confirmation</p>
                    </td>
                </tr>

                <!-- Greeting -->
                <tr>
                    <td style="padding:20px;">
                        <p>Hi there,</p>
                        <p>Thank you for shopping with <strong>Qdio</strong> 🎉</p>
                        <p>Your order <strong>#{order_id}</strong> has been successfully placed.</p>
                    </td>
                </tr>

                <!-- Order Items -->
                <tr>
                    <td style="padding:0 20px 20px;">
                        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                            <tr style="background:#f2f2f2;">
                                <th style="padding:10px;text-align:left;">Item</th>
                                <th style="padding:10px;text-align:center;">Qty</th>
                                <th style="padding:10px;text-align:right;">Price</th>
                            </tr>
                            {items_html}
                        </table>
                    </td>
                </tr>

                <!-- Total -->
                <tr>
                    <td style="padding:20px;text-align:right;">
                        <h3 style="margin:0;">Total: ₹{total_amount}</h3>
                    </td>
                </tr>

                <!-- Footer -->
                <tr>
                    <td style="padding:20px;background:#fafafa;font-size:12px;color:#666;text-align:center;">
                        <p>If you have any questions, contact us at support@qdio.shop</p>
                        <p>© {datetime.now().year} Qdio. All rights reserved.</p>
                    </td>
                </tr>

            </table>
        </body>
        </html>
        """

        ses_client.send_email(
            Source=f"QDIO <{os.getenv('SES_FROM_EMAIL')}>",
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Html": {"Data": body_html}},
            },
        )

    except Exception as e:
        print("SES Email Error:", e)