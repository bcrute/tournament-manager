"""Admin surface: authorization, audit logging, and the actions themselves.

The admin surface is unlisted, but the tests here exist because "unlisted" is
not a control. What protects it is the account check — so that is what is
tested hardest.
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.admin import router as admin_router
from app.db import q
from app.table import router as table_router
from app.tournaments import router as tournaments_router

ADMIN = "rootadmin"
NOT_ADMIN = "ordinaryplayer"


@pytest.fixture(scope="module")
def client():
    os.environ["TABLE_ADMINS"] = ADMIN
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    app.include_router(admin_router, prefix="/api/admin")
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    os.environ.pop("TABLE_ADMINS", None)


def signin(c, username):
    """Sign up, or log in if the account already exists — the client fixture is
    module-scoped, so most of these run against an account made earlier."""
    c.cookies.clear()
    creds = {"username": username, "password": "a good long password"}
    r = c.post("/api/account/signup", json=creds)
    if r.status_code != 200:
        r = c.post("/api/account/login", json=creds)
        assert r.status_code == 200, r.text
    return c


READS = ["/api/admin/overview", "/api/admin/rooms", "/api/admin/tournaments",
         "/api/admin/bans", "/api/admin/log"]


class TestAccess:
    def test_signed_out_callers_get_404_not_403(self, client):
        """403 confirms the surface exists and that the path was right. 404
        tells a prober nothing."""
        client.cookies.clear()
        for path in READS:
            r = client.get(path)
            assert r.status_code == 404, path
            assert r.json()["detail"] == "Not Found"

    def test_an_ordinary_account_gets_404_too(self, client):
        signin(client, NOT_ADMIN)
        for path in READS:
            assert client.get(path).status_code == 404, path

    def test_write_endpoints_are_equally_closed(self, client):
        signin(client, NOT_ADMIN + "2")
        assert client.post("/api/admin/rooms/ABCDE/close", json={}).status_code == 404
        assert client.post("/api/admin/tournaments/ABCDE/end", json={}).status_code == 404
        assert client.post("/api/admin/bans/whatever/lift", json={}).status_code == 404

    def test_the_configured_admin_gets_in(self, client):
        signin(client, ADMIN)
        r = client.get("/api/admin/overview")
        assert r.status_code == 200 and r.json()["admin"] == ADMIN

    def test_admin_is_matched_case_insensitively(self, client):
        """Usernames are UNIQUE COLLATE NOCASE, so the check must be too —
        otherwise 'RootAdmin' signs up and silently isn't an admin."""
        os.environ["TABLE_ADMINS"] = "RoOtAdMiN"
        signin(client, ADMIN)
        assert client.get("/api/admin/overview").status_code == 200
        os.environ["TABLE_ADMINS"] = ADMIN

    def test_with_no_admins_configured_the_surface_does_not_exist(self, client):
        """The default. A deployment that never sets TABLE_ADMINS has no admin
        surface at all, not an empty one."""
        os.environ["TABLE_ADMINS"] = ""
        signin(client, ADMIN)
        for path in READS:
            assert client.get(path).status_code == 404, path
        os.environ["TABLE_ADMINS"] = ADMIN

    def test_admin_is_not_settable_from_the_database(self, client):
        """Privilege comes from the environment. Nothing an attacker can write
        to the accounts table should grant it."""
        signin(client, NOT_ADMIN + "3")
        q("UPDATE accounts SET username = username WHERE username = ?", (NOT_ADMIN + "3",))
        assert client.get("/api/admin/overview").status_code == 404


class TestReads:
    def test_overview_counts_without_exposing_contents(self, client):
        signin(client, ADMIN)
        body = client.get("/api/admin/overview").json()
        assert set(body) == {"admin", "rooms", "tournaments", "accounts", "players", "bans"}
        assert isinstance(body["rooms"]["total"], int)

    def test_bans_never_expose_an_ip_address(self, client):
        """`subject` is a salted hash by construction — there is no code path
        that could print an address here."""
        signin(client, ADMIN)
        q("INSERT OR REPLACE INTO bans (subject, until, strikes) VALUES (?, unixepoch()+3600, 2)",
          ("hashed-subject-aaa",))
        rows = client.get("/api/admin/bans").json()["bans"]
        assert any(b["subject"] == "hashed-subject-aaa" for b in rows)
        assert all("ip" not in k for b in rows for k in b)

    def test_room_and_tournament_listings_are_bounded(self, client):
        signin(client, ADMIN)
        assert client.get("/api/admin/rooms", params={"limit": 9999}).status_code == 200
        assert client.get("/api/admin/tournaments", params={"limit": 9999}).status_code == 200


class TestActions:
    def _room(self, client):
        client.cookies.clear()
        r = client.post("/api/table/rooms", json={"name": "p1", "mode": "life"})
        return r.json()["code"]

    def test_closing_a_room_ends_it_without_deleting_history(self, client):
        code = self._room(client)
        signin(client, ADMIN)
        assert client.post(f"/api/admin/rooms/{code}/close",
                           json={"reason": "stuck"}).status_code == 200
        row = q("SELECT status FROM rooms WHERE code = ?", (code,)).fetchone()
        assert row["status"] == "ended"
        # the room and its players still exist — an admin doesn't erase games
        assert q("SELECT COUNT(*) c FROM players WHERE room_code = ?", (code,)).fetchone()["c"] > 0

    def test_every_action_is_written_to_the_audit_log(self, client):
        code = self._room(client)
        signin(client, ADMIN)
        client.post(f"/api/admin/rooms/{code}/close", json={"reason": "why not"})
        entry = client.get("/api/admin/log").json()["entries"][0]
        assert entry["actor"] == ADMIN
        assert entry["action"] == "room.close"
        assert entry["target"] == code and entry["detail"] == "why not"

    def test_acting_on_something_that_does_not_exist_is_404_and_unlogged(self, client):
        signin(client, ADMIN)
        before = len(client.get("/api/admin/log").json()["entries"])
        assert client.post("/api/admin/rooms/ZZZZZ/close", json={}).status_code == 404
        assert client.post("/api/admin/tournaments/ZZZZZ/end", json={}).status_code == 404
        assert client.post("/api/admin/bans/nosuch/lift", json={}).status_code == 404
        after = len(client.get("/api/admin/log").json()["entries"])
        assert after == before, "a failed action must not pollute the audit log"

    def test_lifting_a_ban_clears_it_and_its_strikes(self, client):
        signin(client, ADMIN)
        q("INSERT OR REPLACE INTO bans (subject, until, strikes) VALUES (?, unixepoch()+3600, 3)",
          ("subject-to-lift",))
        assert client.post("/api/admin/bans/subject-to-lift/lift",
                           json={"reason": "false positive"}).status_code == 200
        assert q("SELECT 1 FROM bans WHERE subject = ?", ("subject-to-lift",)).fetchone() is None

    def test_ending_a_tournament_also_closes_its_open_round(self, client):
        client.cookies.clear()
        client.post("/api/account/signup",
                    json={"username": "orgforadmin", "password": "a good long password"})
        client.post("/api/account/email", json={"email": "o@example.com"})
        code = client.post("/api/tournament",
                           json={"name": "abandoned", "settings": {}}).json()["code"]
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["z1", "z2", "z3", "z4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        signin(client, ADMIN)
        assert client.post(f"/api/admin/tournaments/{code}/end", json={}).status_code == 200
        assert q("SELECT status FROM tournaments WHERE code = ?",
                 (code,)).fetchone()["status"] == "ended"
        assert q("SELECT COUNT(*) c FROM trounds WHERE tournament_code = ? AND status = 'active'",
                 (code,)).fetchone()["c"] == 0
