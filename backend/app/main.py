from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .table import router as table_router

app = FastAPI(title="mtg")

app.include_router(table_router, prefix="/api/table")


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
