import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .access_log import install as install_access_log_redaction
from .accounts import router as accounts_router
from .admin import router as admin_router
from .db import q
from .limits import RateLimiter, classify, client_id, client_ip
from .table import router as table_router
from .tournaments import router as tournaments_router

# The interactive docs and schema are development conveniences. In production
# they enumerate every route, parameter and model on an otherwise hardened box —
# free reconnaissance for anyone probing it. Authentication still holds without
# them, so the loss is an attacker's map, not a user's feature.
_DEV_DOCS = os.environ.get("TABLE_DEV_DOCS", "off") == "on"

# Entrant tokens ride in the query string (§1), and uvicorn's access log writes
# the full request target. Installed at import time — before the first request
# is served under any runner — so no line is ever written with a live token in
# it. See access_log.py for why this lives in the app and not only in the proxy.
install_access_log_redaction()

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
# unlisted; authorization is in admin.require_admin, not in the absence of a link
app.include_router(admin_router, prefix="/api/admin")


_last_prune = 0.0


# The browser-enforced half of the privacy position. The app claims no
# third-party requests and no tracking; a Content-Security-Policy is what makes
# that a rule the browser applies rather than a promise we make. Set here, in
# the repo, rather than in a proxy config — so it is reviewable and testable
# alongside the code it protects.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # inline *attributes* (style={{…}}) are used throughout the seat layout
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        # the QR scanner attaches a MediaStream to a <video>
        "media-src 'self' blob:",
        "font-src 'self'",
        # same-origin only: this is what forbids a CDN or an analytics beacon
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    # never send our URLs to anyone. Room addresses are opaque ids now, and
    # this keeps them from travelling in a Referer even so.
    "Referrer-Policy": "no-referrer",
    # deny every capability except the camera, which the QR scanner asks for
    "Permissions-Policy": (
        "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), "
        "interest-cohort=(), browsing-topics=()"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


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
                # deep link into client routing — still index.html, so it must
                # carry the same no-cache header the entry point does
                return self._cache(path, await super().get_response("index.html", scope))
            raise
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
        return self._cache(path, response)

    @staticmethod
    def _cache(path: str, response):
        """Cache the fingerprinted assets hard, and never the entry point.

        Vite hashes every file under /assets, so those are safe to cache
        forever — the name changes when the content does. index.html must NOT
        be cached: it is the only thing that knows which hashed bundle is
        current, and without an explicit header browsers apply heuristic
        caching and keep loading a stale one. A deploy then lands on the server
        and never reaches the user, which is exactly what happened.
        """
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


# Configurable so end-to-end tests can serve the real built frontend from
# frontend/dist without a copy step. Production leaves it at the default.
_STATIC_DIR = os.environ.get("TABLE_STATIC_DIR", "static")

if os.path.isdir(_STATIC_DIR):
    app.mount("/", SPAStaticFiles(directory=_STATIC_DIR, html=True), name="static")
