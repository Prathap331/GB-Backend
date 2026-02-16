# main.py
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.auth_routers import router as auth_router
from routers.profiles_routers import router as profiles_router
from routers.partners_routers import router as partners_router
from routers.orders_routers import router as orders_router
from routers.products_routers import router as products_router
from routers.suppliers_routers import router as suppliers_router
from routers.returns_routers import router as returns_router
from routers.admin_routers import router as admin_router
from routers.shopify_routers import router as shopify_router

app = FastAPI(title="QDIO E-Commerce")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://qdio.in",
        "https://www.qdio.in",
        "https://qdio.shop",
        "https://www.qdio.shop",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://localhost:8080",

        
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(tags=["test"])


@router.get("/")
def read_root():
    return {"message": "Welcome to the E-Commerce API v3 (Razorpay)"}


app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(orders_router)
app.include_router(partners_router)
app.include_router(returns_router)
app.include_router(products_router)
app.include_router(admin_router)
app.include_router(suppliers_router)
app.include_router(shopify_router)