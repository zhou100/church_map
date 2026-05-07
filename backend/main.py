from backend.env_loader import load_env_local

load_env_local()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend import deps
from backend.routers import churches, reviews, auth

app = FastAPI(title="HolyHub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(churches.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(auth.router, prefix="/api")


@app.on_event("startup")
def startup():
    deps.db.connect()


@app.get("/api/health")
def health():
    return {"status": "ok"}
