"""FastAPI application entry point: ``uvicorn app.main:app --reload``."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ask, ipos
from app.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="IPO Tracker API",
    description="How Indian IPOs performed for each investor category, on listing day, today and any date in between.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(ipos.router)
app.include_router(ask.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}
