"""App shell: health and SPA static fallback."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def main_client(tmp_path_factory):
    # main.py serves ./static at import time — provide one
    static = tmp_path_factory.mktemp("static_root") / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>SPA-INDEX</body></html>")
    (static / "real.txt").write_text("real file")
    old_cwd = os.getcwd()
    os.chdir(static.parent)
    from app.main import app

    with TestClient(app) as c:
        yield c
    os.chdir(old_cwd)


class TestShell:
    def test_health(self, main_client):
        r = main_client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "app": "mtg"}

    def test_static_file_served(self, main_client):
        r = main_client.get("/real.txt")
        assert r.status_code == 200 and r.text == "real file"

    def test_spa_fallback_serves_index_for_client_routes(self, main_client):
        for route in ("/table", "/table/r/ABCDE", "/deep/unknown/path"):
            r = main_client.get(route)
            assert r.status_code == 200 and "SPA-INDEX" in r.text

    def test_rate_limit_returns_429_with_retry_after(self, main_client):
        import app.main as m
        from app.limits import RateLimiter

        original = m.limiter
        m.limiter = RateLimiter(rules={"normal": (2, 60), "sensitive": (1, 60), "socket": (1, 60)})
        try:
            assert main_client.get("/api/health").status_code == 200
            assert main_client.get("/api/health").status_code == 200
            r = main_client.get("/api/health")
            assert r.status_code == 429
            assert int(r.headers["Retry-After"]) >= 1
        finally:
            m.limiter = original

    def test_static_assets_are_not_rate_limited(self, main_client):
        """Card images and the bundle must stay fast even under a strict limit."""
        import app.main as m
        from app.limits import RateLimiter

        original = m.limiter
        m.limiter = RateLimiter(rules={"normal": (1, 60), "sensitive": (1, 60), "socket": (1, 60)})
        try:
            for _ in range(5):
                assert main_client.get("/real.txt").status_code == 200
        finally:
            m.limiter = original

    def test_no_third_party_card_proxy(self, main_client):
        """The Scryfall proxy was removed; make sure it stays gone."""
        r = main_client.get("/api/random-card")
        assert "SPA-INDEX" in r.text  # falls through to the SPA, no API route


class TestSchemaExposure:
    """The schema and interactive docs are dev conveniences. Serving them in
    production hands an attacker a complete route and model map."""

    def _app(self, dev_docs: str):
        import importlib
        import os
        os.environ["TABLE_DEV_DOCS"] = dev_docs
        from app import main as main_mod
        importlib.reload(main_mod)
        return main_mod.app

    def test_schema_and_docs_are_off_by_default(self):
        from fastapi.testclient import TestClient
        with TestClient(self._app("off"), base_url="https://testserver") as c:
            for path in ("/openapi.json", "/docs", "/redoc"):
                # the SPA fallback may answer, but the schema itself must not
                r = c.get(path)
                assert "paths" not in (r.json() if r.headers.get(
                    "content-type", "").startswith("application/json") else {}), path

    def test_they_can_be_enabled_for_development(self):
        from fastapi.testclient import TestClient
        with TestClient(self._app("on"), base_url="https://testserver") as c:
            r = c.get("/openapi.json")
            assert r.status_code == 200 and "paths" in r.json()

    def teardown_method(self):
        import importlib
        import os
        os.environ["TABLE_DEV_DOCS"] = "off"
        from app import main as main_mod
        importlib.reload(main_mod)


class TestStaticCaching:
    """A deploy that the browser never fetches is not a deploy."""

    def _client(self, tmp_path):
        import os
        from fastapi.testclient import TestClient
        from app.main import SPAStaticFiles
        from fastapi import FastAPI
        d = tmp_path / "static"
        (d / "assets").mkdir(parents=True)
        (d / "index.html").write_text("<!doctype html><html></html>")
        (d / "assets" / "index-abc123.js").write_text("console.log(1)")
        app = FastAPI()
        app.mount("/", SPAStaticFiles(directory=str(d), html=True), name="static")
        os.chdir(tmp_path)
        return TestClient(app)

    def test_index_is_never_cached(self, tmp_path):
        c = self._client(tmp_path)
        assert c.get("/").headers["cache-control"] == "no-cache"

    def test_the_spa_fallback_is_never_cached_either(self, tmp_path):
        """An unknown route returns index.html; caching that would pin a stale
        bundle for every deep link too."""
        c = self._client(tmp_path)
        r = c.get("/table/r/ABCDE")
        assert r.headers["cache-control"] == "no-cache"

    def test_hashed_assets_are_cached_hard(self, tmp_path):
        c = self._client(tmp_path)
        cc = c.get("/assets/index-abc123.js").headers["cache-control"]
        assert "immutable" in cc and "max-age=31536000" in cc
