import os
import tempfile

os.environ["TREACHERY_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.table import router  # noqa: E402  (env must be set before import)

app = FastAPI()
app.include_router(router, prefix="/api/table")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def public_id(room: str) -> str:
    """The room's public identifier, from whichever handle a test is holding.

    Tests mostly hold the five-character internal code, because that is what
    `create()` returns and what every authenticated route keys on. The code is
    no longer a join credential, so this translates — something a harness with
    database access may legitimately do and a client cannot. Anything that is
    already a `url_id` passes straight through.

    That the code itself opens nothing is pinned separately, in
    `test_table.py::test_the_five_character_code_no_longer_joins_anything`.
    """
    from app.db import q as dbq

    if len(room) == 5:
        row = dbq("SELECT url_id FROM rooms WHERE code = ?", (room.upper(),)).fetchone()
        if row and row["url_id"]:
            return row["url_id"]
    return room


class Api:
    """Small wrapper: token-aware calls against /api/table."""

    def __init__(self, client: TestClient):
        self.c = client

    def call(self, method, path, token=None, body=None, expect=200):
        headers = {"X-Player-Token": token} if token else {}
        r = self.c.request(method, f"/api/table{path}", json=body, headers=headers)
        assert r.status_code == expect, f"{method} {path} -> {r.status_code}: {r.text}"
        return r.json()

    def create(self, name="host", mode="life", display=False, expect=200):
        return self.call(
            "POST", "/rooms", body={"name": name, "mode": mode, "display": display}, expect=expect
        )

    def join(self, room, name, display=False, expect=200):
        """Join by the room's public identifier.

        Most tests hold the five-character internal code, because that is what
        `create()` hands back and what every authenticated route keys on. The
        code is no longer a join credential, so this translates it — a thing a
        harness with database access may legitimately do, and a client cannot.
        Pass a `url_id` directly and it is used as-is.

        The property that matters is pinned separately, in
        `test_table.py::test_the_five_character_code_no_longer_joins_anything`.
        """
        return self.call(
            "POST",
            "/rooms/join",
            body={"roomId": public_id(room), "name": name, "display": display},
            expect=expect,
        )

    def seats(self, room, expect=200):
        return self.call(
            "POST", "/rooms/seats", body={"roomId": public_id(room)}, expect=expect
        )

    def reclaim(self, room, pid, force=False, expect=200):
        return self.call(
            "POST",
            "/rooms/reclaim",
            body={"roomId": public_id(room), "pid": pid, "force": force},
            expect=expect,
        )

    def me(self, code, token, expect=200):
        return self.call("GET", f"/rooms/{code}/me", token=token, expect=expect)

    def start(self, code, token, expect=200):
        return self.call("POST", f"/rooms/{code}/start", token=token, expect=expect)

    def pid_of(self, code, token, name):
        s = self.me(code, token)
        return next(p["pid"] for p in s["players"] if p["name"] == name)


@pytest.fixture
def api(client):
    return Api(client)


@pytest.fixture
def life_room(api):
    """A started 3-player life room: (code, tokens dict)."""
    r = api.create("host", "life")
    code = r["code"]
    tokens = {"host": r["playerToken"]}
    for n in ("p2", "p3"):
        tokens[n] = api.join(code, n)["playerToken"]
    api.start(code, tokens["host"])
    return code, tokens


@pytest.fixture
def treachery_room(api):
    """A started 5-player treachery room: (code, tokens dict)."""
    r = api.create("host", "treachery")
    code = r["code"]
    tokens = {"host": r["playerToken"]}
    for n in ("p2", "p3", "p4", "p5"):
        tokens[n] = api.join(code, n)["playerToken"]
    api.start(code, tokens["host"])
    return code, tokens
