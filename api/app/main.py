"""FastAPI application entrypoint: search/browse/detail/identity/watch/
channel/auth endpoints over the FCC ULS Explorer database."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import close_pool, open_pool
from .routers import amateur, auth, channels, identity, search, towers, watches


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    yield
    await close_pool()


app = FastAPI(title="FCC ULS Explorer API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(amateur.router)
app.include_router(towers.router)
app.include_router(identity.router)
app.include_router(auth.router)
app.include_router(watches.router)
app.include_router(channels.router)


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}
