"""FastAPI application entrypoint: search/browse/detail/identity/watch/
channel/auth endpoints over the FCC ULS Explorer database."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .admin_auth import init_admin_password
from .config import settings
from .db import close_pool, open_pool
from .ratelimit import close_redis
from .routers import admin, amateur, auth, channels, identity, search, towers, watches


@asynccontextmanager
async def lifespan(app: FastAPI):
    _guard_default_session_secret()
    init_admin_password()
    await open_pool()
    yield
    await close_pool()
    await close_redis()


def _guard_default_session_secret() -> None:
    """Refuse to start if the session-signing secret is left at its
    insecure placeholder default or empty. This one value signs both the
    user session cookie and the admin session cookie (see app.security),
    so leaving it default would let anyone forge valid sessions for any
    user, or for the admin panel."""
    if not settings.session_secret or settings.session_secret == "change-me-in-production":
        raise RuntimeError(
            "FCCULS_SESSION_SECRET is not set (or is left at its insecure "
            "default 'change-me-in-production'). Set a long, random value "
            "for FCCULS_SESSION_SECRET in your .env before starting this "
            "service -- refusing to start with an insecure/default secret."
        )


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
app.include_router(admin.router)


@app.get("/api/healthz")
async def healthz():
    return {"status": "ok"}
