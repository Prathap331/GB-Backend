# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import router as api_router
from shopify_routers import router as shopify_router

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




app.include_router(api_router)

app.include_router(shopify_router)