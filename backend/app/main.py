import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


app = FastAPI(
    title="Wind Forecast Analytics API",
    description="API scaffolding for historical UK wind forecast analysis.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)
