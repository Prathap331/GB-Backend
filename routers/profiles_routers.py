from fastapi import APIRouter, Depends, HTTPException
from fastapi import HTTPException
from services import (
    get_user_supabase,
    get_current_user
)
from schemas.auth_schemas import (
    Profile, ProfileBase,UserResponse
)


router = APIRouter(prefix="/profiles", tags=["Profiles"])

# --- Profile Endpoints ---
@router.get("/me", response_model=Profile)
async def get_my_profile(user: UserResponse = Depends(get_current_user)):
    """
    Get the profile of the currently authenticated user. 
    This endpoint uses the user's JWT token to fetch their profile information from the Supabase database. 
    If the profile does not exist (e.g., first login via Google), it automatically creates a new profile with default values and returns it. 
    This ensures that every authenticated user has an associated profile in the system.
    """
    sb = get_user_supabase(user.token)  # 🔐 anon + JWT (RLS enforced)

    res = (
        sb
        .table("profiles")
        .select("*")
        .eq("id", str(user.id))
        .maybe_single()
        .execute()
    )

    # Auto-create profile (Google / first login)
    if not res or not res.data:
        profile = {
            "id": str(user.id),
            "full_name": user.email.split("@")[0],
            "email": user.email,
            "account_status": "active",
        }

        insert_res = sb.table("profiles").insert(profile).execute()
        return insert_res.data[0]

    return res.data


@router.put("/me", response_model=Profile)
async def update_my_profile(
    profile: ProfileBase,
    user: UserResponse = Depends(get_current_user)
):
    """Update the profile of the currently authenticated user."""

    sb = get_user_supabase(user.token)

    update_data = profile.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No update data provided")

    res = (
        sb
        .table("profiles")
        .update(update_data)
        .eq("id", str(user.id))
        .execute()
    )

    if not res.data:
        raise HTTPException(404, "Profile update failed")

    return res.data[0]

