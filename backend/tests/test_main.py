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
