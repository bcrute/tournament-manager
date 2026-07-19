import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .accounts import router as accounts_router
from .db import q
from .limits import RateLimiter, classify, client_id, client_ip
from .table import router as table_router
from .tournaments import router as tournaments_router

# The interactive docs and schema are development conveniences. In production
# they enumerate every route, parameter and model on an otherwise hardened box —
# free reconnaissance for anyone probing it. Authentication still holds without
# them, so the loss is an attacker's map, not a user's feature.
_DEV_DOCS = os.environ.get("TABLE_DEV_DOCS", "off") == "on"

app = FastAPI(
    title="mtg",
    openapi_url="/openapi.json" if _DEV_DOCS else None,
    docs_url="/docs" if _DEV_DOCS else None,
    redoc_url="/redoc" if _DEV_DOCS else None,
)

# Counters are per-process; a second worker would need a shared store.
limiter = RateLimiter(db=q) if os.environ.get("TABLE_RATELIMIT", "on") != "off" else None
app.state.limiter = limiter  # websocket handler reads it from here

app.include_router(table_router, prefix="/api/table")
app.include_router(accounts_router, prefix="/api/account")
app.include_router(tournaments_router, prefix="/api/tournament")


_last_prune = 0.0


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Limit API traffic per client. Static assets are left alone — they are
    cached by browsers and cheap to serve."""
    if limiter is None or not request.url.path.startswith("/api/"):
        return await call_next(request)
    # housekeeping: drop idle counters and ban records past their retention
    global _last_prune
    now = time.time()
    if now - _last_prune > 3600:
        _last_prune = now
        limiter.prune()
    cid = client_id(client_ip(request))
    allowed, retry = limiter.check(cid, classify(request.url.path, request.method))
    if not allowed:
        return JSONResponse(
            {"detail": "too many requests — slow down"},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "mtg"}


class SPAStaticFiles(StaticFiles):
    """Serve the built frontend; unknown paths fall back to index.html for client routing."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


app.mount("/", SPAStaticFiles(directory="static", html=True), name="static")
