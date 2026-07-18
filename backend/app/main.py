from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .treachery import router as treachery_router

SCRYFALL_RANDOM = "https://api.scryfall.com/cards/random"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=10)
    yield
    await app.state.http.aclose()


app = FastAPI(title="mtg", lifespan=lifespan)

app.include_router(treachery_router, prefix="/api/treachery")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "mtg"}


@app.get("/api/random-card")
async def random_card():
    try:
        r = await app.state.http.get(SCRYFALL_RANDOM)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"scryfall error: {exc}")
    card = r.json()
    return {
        "name": card.get("name"),
        "set_name": card.get("set_name"),
        "type_line": card.get("type_line"),
        "oracle_text": card.get("oracle_text"),
        "image": (card.get("image_uris") or {}).get("normal")
        or ((card.get("card_faces") or [{}])[0].get("image_uris") or {}).get("normal"),
        "scryfall_uri": card.get("scryfall_uri"),
    }


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
