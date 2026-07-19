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

    def test_no_third_party_card_proxy(self, main_client):
        """The Scryfall proxy was removed; make sure it stays gone."""
        r = main_client.get("/api/random-card")
        assert "SPA-INDEX" in r.text  # falls through to the SPA, no API route
