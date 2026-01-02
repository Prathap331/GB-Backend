# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import router as api_router

app = FastAPI(title="E-Commerce Backend v3 (Razorpay)")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




app.include_router(api_router)

