"""FastAPI entry point. Run locally with:  uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load settings at startup so a missing secret stops the app immediately,
    # instead of failing later on the first request.
    app.state.settings = get_settings()
    yield


app = FastAPI(title="CareLens", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
