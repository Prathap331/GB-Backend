from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer

from fastapi import Header, HTTPException
import asyncio
from supabase import create_client
from services import (
    get_user_supabase,
    supabase_admin,
    supabase_db,
    get_current_user,
    supabase_anon
)
from schemas.auth_schemas import (
    UserCreate, UserForgotPassword, UserResetPassword, UserResponse
)
from schemas.admin_schemas import Token

from services import (
    SUPABASE_URL, SUPABASE_ANON_KEY,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")



# AUTH ROUTERS

@router.post("/signup", response_model=UserResponse)
async def signup(user: UserCreate):
    """
    Signup flow:
    1️⃣ Validate partner_code (optional)
    2️⃣ Create auth user (Supabase anon client)
    3️⃣ WAIT for auth.users commit (VERY IMPORTANT)
    4️⃣ Upsert profile (Supabase service role)
    5️⃣ Always return success if auth succeeded

    """
    partner_id = None

    # -------------------------
    # 1️⃣ Validate partner_code (SERVER DB – service role)
    # -------------------------
    if user.partner_code:
        partner_res = (
            supabase_admin
            .table("partners")
            .select("partner_id")
            .eq("partner_code", user.partner_code.upper())
            .maybe_single()
            .execute()
        )

        if not partner_res or not partner_res.data:
            raise HTTPException(status_code=400, detail="Invalid partner code")

        partner_id = partner_res.data["partner_id"]

   
    # -------------------------
    # 2️⃣ Auth signup (PUBLIC – anon client)
    # -------------------------
    res = supabase_anon.auth.sign_up({
        "email": user.email,
        "password": user.password,
        "options": {
            "data": {
                "full_name": user.full_name,
                "phone": user.phone_number
            }
        }
    })

    # IMPORTANT: signup either succeeds or raises
    if not res or not res.user:
        raise HTTPException(status_code=400, detail="Signup failed")

    user_id = res.user.id
    print("DEBUG | auth user_id:", user_id)

    # -------------------------
    # 3️⃣ WAIT for auth.users commit (VERY IMPORTANT)
    # -------------------------
    # Email verification ON → needs more time
    await asyncio.sleep(1.0)

    # -------------------------
    # 4️⃣ Upsert profile (SERVER DB – service role)
    #     ❗ NEVER fail signup if this fails
    # -------------------------
    profile_payload = {
        "id": user_id,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "email": user.email,
        "is_partner": bool(partner_id),
        "partner_id": partner_id,
    }

    try:
        upsert_res = (
            supabase_db
            .table("profiles")
            .upsert(profile_payload, on_conflict="id")
            .execute()
        )
        print("DEBUG | profile upsert response:", upsert_res.data)

    except Exception as e:
        # ❗ DO NOT raise — auth already succeeded
        print("PROFILE UPSERT FAILED (will retry later):", e)

    # -------------------------
    # 5️⃣ Always return success if auth succeeded
    # -------------------------
    return UserResponse(
        id=user_id,
        email=user.email,
        created_at=res.user.created_at
    )


# login
@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        
        res = supabase_anon.auth.sign_in_with_password({
            "email": form_data.username,
            "password": form_data.password
        })

        return Token(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            token_type="bearer"
        )

    except Exception as e:
        print("❌ LOGIN ERROR:", str(e))
        raise HTTPException(400, "Incorrect email or password")



@router.get("/me")
async def me(user: UserResponse = Depends(get_current_user)):
    """
    Get current user profile
    """
    sb = get_user_supabase(user.token)

    res = (
        sb
        .table("profiles")
        .select("full_name, email, is_partner, partner_id")
        .eq("id", str(user.id))
        .maybe_single()
        .execute()
    )

    if res and res.data:
        profile = res.data

    return {
        "id": user.id,
        "email": user.email,
        **profile
    }


@router.post("/forgot-password")
async def forgot_password(data: UserForgotPassword):
    """
    Trigger a password reset email via Supabase
    Handles rate limiting errors gracefully.
    """
    try:
        # UPDATE: Set the redirect URL explicitly.
        # Change this URL to your actual frontend reset page.
        # Example for local testing: "http://localhost:3000/reset-password"
        # Example for production: "https://goldenbanana.vercel.app/reset-password"  
        redirect_url = "https://www.qdio.shop/reset-password" 
        
        supabase_admin.auth.reset_password_email(data.email, options={"redirectTo": redirect_url})
    

       

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



@router.post("/reset-password")
async def reset_password(
    data: UserResetPassword,
    token: str = Depends(oauth2_scheme)
):
    """
    Reset the user's password using the token from the reset email.
    The frontend should have a page that captures the new password and the token from the URL,
    then calls this endpoint to perform the reset.
    """
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


