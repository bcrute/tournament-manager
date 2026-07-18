"""App shell: health, scryfall proxy, SPA static fallback."""

import os

import httpx
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


class FakeResponse:
    def __init__(self, payload, fail=False):
        self._payload = payload
        self._fail = fail

    def raise_for_status(self):
        if self._fail:
            raise httpx.HTTPError("upstream down")

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, payload, fail=False):
        self._payload = payload
        self._fail = fail

    async def get(self, url):
        return FakeResponse(self._payload, self._fail)

    async def aclose(self):
        pass


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

    def test_random_card_shapes_scryfall_payload(self, main_client):
        from app.main import app

        app.state.http = FakeHttp(
            {
                "name": "Black Lotus",
                "set_name": "Alpha",
                "type_line": "Artifact",
                "oracle_text": "Sacrifice: add three mana.",
                "image_uris": {"normal": "https://img/x.jpg"},
                "scryfall_uri": "https://scryfall.com/x",
            }
        )
        r = main_client.get("/api/random-card")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Black Lotus" and body["image"] == "https://img/x.jpg"

    def test_random_card_double_faced_fallback(self, main_client):
        from app.main import app

        app.state.http = FakeHttp(
            {
                "name": "Delver",
                "card_faces": [{"image_uris": {"normal": "https://img/face.jpg"}}],
                "scryfall_uri": "https://scryfall.com/d",
            }
        )
        body = main_client.get("/api/random-card").json()
        assert body["image"] == "https://img/face.jpg"

    def test_random_card_upstream_error_is_502(self, main_client):
        from app.main import app

        app.state.http = FakeHttp({}, fail=True)
        assert main_client.get("/api/random-card").status_code == 502
