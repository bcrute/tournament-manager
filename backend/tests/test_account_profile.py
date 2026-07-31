"""The account's own profile: renaming, the default table name, and totals.

Two names live on an account and they are not interchangeable. `username` is
typed to sign in — unique, case-insensitively, and changing it is the one edit
the owner cannot undo unaided, so it costs a password. `display_name` is read
aloud by the other four people at the table — cosmetic, duplicable, and free to
change.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.table import router as table_router


@pytest.fixture(scope="module")
def app_client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    # the session cookie is Secure, so a client on http would refuse to store it
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def fresh(app_client):
    app_client.cookies.clear()
    return app_client


PASSWORD = "correct horse battery"


def signup(c, username, password=PASSWORD):
    return c.post("/api/account/signup", json={"username": username, "password": password})


class TestRename:
    def test_renames_and_the_new_name_signs_in(self, fresh):
        signup(fresh, "renamer.one")
        r = fresh.post("/api/account/username",
                       json={"username": "renamed.one", "password": PASSWORD})
        assert r.status_code == 200
        assert r.json()["account"]["username"] == "renamed.one"

        fresh.cookies.clear()
        assert fresh.post("/api/account/login",
                          json={"username": "renamed.one", "password": PASSWORD}).status_code == 200

    def test_the_old_name_stops_working(self, fresh):
        signup(fresh, "renamer.two")
        fresh.post("/api/account/username",
                   json={"username": "renamed.two", "password": PASSWORD})
        fresh.cookies.clear()
        r = fresh.post("/api/account/login", json={"username": "renamer.two", "password": PASSWORD})
        assert r.status_code == 401

    def test_a_wrong_password_is_refused(self, fresh):
        """A session cookie alone must not be able to rename the account: it is
        the first move in a takeover and the owner cannot undo it."""
        signup(fresh, "renamer.three")
        r = fresh.post("/api/account/username",
                       json={"username": "stolen.three", "password": "not the password"})
        assert r.status_code == 403
        assert fresh.get("/api/account/me").json()["account"]["username"] == "renamer.three"

    def test_a_failed_rename_is_recorded_without_the_password(self, fresh):
        signup(fresh, "renamer.logged")
        fresh.post("/api/account/username",
                   json={"username": "whatever.logged", "password": "wrong one entirely"})
        rows = q("SELECT subject, detail FROM security_log WHERE kind = 'auth.fail' "
                 "ORDER BY id DESC LIMIT 5").fetchall()
        assert any(r["subject"] == "renamer.logged" and r["detail"] == "username-change"
                   for r in rows)
        assert not any(r["detail"] and "wrong one entirely" in r["detail"] for r in rows)

    def test_a_taken_name_is_refused(self, fresh):
        signup(fresh, "occupied.name")
        fresh.cookies.clear()
        signup(fresh, "renamer.four")
        r = fresh.post("/api/account/username",
                       json={"username": "occupied.name", "password": PASSWORD})
        assert r.status_code == 409

    def test_a_taken_name_is_refused_regardless_of_case(self, fresh):
        """The unique index is NOCASE, so the check has to be too — otherwise
        the insert fails with a 500 instead of a clear 409."""
        signup(fresh, "MixedCase.Taken")
        fresh.cookies.clear()
        signup(fresh, "renamer.five")
        r = fresh.post("/api/account/username",
                       json={"username": "mixedcase.taken", "password": PASSWORD})
        assert r.status_code == 409

    def test_recasing_your_own_name_is_allowed(self, fresh):
        """Regression: a NOCASE unique index makes an account collide with
        itself unless the clash check excludes the account doing the renaming."""
        signup(fresh, "casechange")
        r = fresh.post("/api/account/username",
                       json={"username": "CaseChange", "password": PASSWORD})
        assert r.status_code == 200
        assert r.json()["account"]["username"] == "CaseChange"

    def test_an_illegal_name_is_refused(self, fresh):
        signup(fresh, "renamer.six")
        r = fresh.post("/api/account/username",
                       json={"username": "no spaces here", "password": PASSWORD})
        assert r.status_code == 400
        assert fresh.get("/api/account/me").json()["account"]["username"] == "renamer.six"

    def test_signed_out_callers_cannot_rename_anyone(self, fresh):
        r = fresh.post("/api/account/username",
                       json={"username": "anything.here", "password": PASSWORD})
        assert r.status_code == 401

    def test_other_sessions_survive_a_rename(self, app_client, fresh):
        """Unlike a password change: the account is the same account, and
        logging every device out for choosing a new name helps nobody."""
        signup(fresh, "renamer.seven")
        other = TestClient(fresh.app, base_url="https://testserver")
        other.post("/api/account/login",
                   json={"username": "renamer.seven", "password": PASSWORD})
        fresh.post("/api/account/username",
                   json={"username": "renamed.seven", "password": PASSWORD})
        assert other.get("/api/account/me").json()["account"]["username"] == "renamed.seven"


class TestDisplayName:
    def test_defaults_to_nothing(self, fresh):
        assert signup(fresh, "namer.one").json()["account"]["displayName"] is None

    def test_sets_and_reads_back(self, fresh):
        signup(fresh, "namer.two")
        r = fresh.post("/api/account/display-name", json={"displayName": "Grumpy Platypus 42"})
        assert r.status_code == 200
        assert r.json()["displayName"] == "Grumpy Platypus 42"
        assert fresh.get("/api/account/me").json()["account"]["displayName"] == "Grumpy Platypus 42"

    def test_clearing_it_returns_to_no_preference(self, fresh):
        signup(fresh, "namer.three")
        fresh.post("/api/account/display-name", json={"displayName": "Sleepy Wombat 11"})
        fresh.post("/api/account/display-name", json={"displayName": "   "})
        assert fresh.get("/api/account/me").json()["account"]["displayName"] is None

    def test_it_cannot_exceed_what_a_table_accepts(self, fresh):
        """A default the join endpoint would reject is worse than no default."""
        signup(fresh, "namer.four")
        r = fresh.post("/api/account/display-name", json={"displayName": "x" * 25})
        assert r.status_code == 422

    def test_the_longest_allowed_name_is_actually_joinable(self, fresh):
        """Pins the two caps together: 24 here must still be 24 at the table."""
        signup(fresh, "namer.five")
        name = "x" * 24
        assert fresh.post("/api/account/display-name",
                          json={"displayName": name}).status_code == 200
        created = fresh.post("/api/table/rooms", json={"name": name, "mode": "life"})
        assert created.status_code == 200

    def test_duplicates_are_fine(self, fresh):
        """Seats are identified by token, never by name — two Grumpy Platypuses
        at one table is a joke, not a collision."""
        signup(fresh, "namer.six")
        fresh.post("/api/account/display-name", json={"displayName": "Same Name 7"})
        fresh.cookies.clear()
        signup(fresh, "namer.seven")
        r = fresh.post("/api/account/display-name", json={"displayName": "Same Name 7"})
        assert r.status_code == 200

    def test_it_needs_no_password(self, fresh):
        """Cosmetic and public: unlike the username, nothing is lost by changing
        it, so it does not carry the username's confirmation cost."""
        signup(fresh, "namer.eight")
        assert fresh.post("/api/account/display-name",
                          json={"displayName": "No Password 3"}).status_code == 200

    def test_signed_out_callers_are_refused(self, fresh):
        assert fresh.post("/api/account/display-name",
                          json={"displayName": "Nope 1"}).status_code == 401


class TestPasswordChangeEndsEverySession:
    """What a password change does to sessions, pinned in full.

    `test_accounts.py` already pins that the caller is signed out. These add
    the parts that were never asserted — that *other* devices go too, and that
    the new password is the one that works — because the settings screen now
    tells the user all three, and copy that promises behaviour has to be
    behaviour that exists.
    """

    def test_every_other_device_is_signed_out(self, fresh):
        signup(fresh, "pw.evictor")
        other = TestClient(fresh.app, base_url="https://testserver")
        other.post("/api/account/login", json={"username": "pw.evictor", "password": PASSWORD})
        assert other.get("/api/account/me").json()["account"] is not None

        fresh.post("/api/account/password",
                   json={"current": PASSWORD, "new": "a brand new password"})
        assert other.get("/api/account/me").json()["account"] is None

    def test_the_caller_is_signed_out_too(self, fresh):
        """Deliberate, and the reason the settings copy says "including this
        one" rather than "your other devices"."""
        signup(fresh, "pw.selfevict")
        fresh.post("/api/account/password",
                   json={"current": PASSWORD, "new": "a brand new password"})
        assert fresh.get("/api/account/me").json()["account"] is None

    def test_the_new_password_is_the_one_that_works(self, fresh):
        signup(fresh, "pw.switcher")
        fresh.post("/api/account/password",
                   json={"current": PASSWORD, "new": "a brand new password"})
        fresh.cookies.clear()
        assert fresh.post("/api/account/login",
                          json={"username": "pw.switcher", "password": PASSWORD}).status_code == 401
        assert fresh.post("/api/account/login",
                          json={"username": "pw.switcher",
                                "password": "a brand new password"}).status_code == 200

    def test_a_wrong_current_password_changes_nothing(self, fresh):
        signup(fresh, "pw.wrong")
        r = fresh.post("/api/account/password",
                       json={"current": "not it at all", "new": "a brand new password"})
        assert r.status_code == 403
        assert fresh.get("/api/account/me").json()["account"] is not None


class TestStats:
    def test_a_new_account_reads_zero_rather_than_empty(self, fresh):
        signup(fresh, "stats.new")
        s = fresh.get("/api/account/stats").json()
        assert s["games"] == 0 and s["tables"] == 0 and s["notes"] == 0
        assert s["byMode"] == {}
        assert s["lastAt"] is None
        assert s["memberSince"] > 0

    def test_counts_seats_tables_and_modes(self, fresh):
        signup(fresh, "stats.player")
        first = fresh.post("/api/table/rooms", json={"name": "Ada", "mode": "life"}).json()
        second = fresh.post("/api/table/rooms", json={"name": "Ada", "mode": "treachery"}).json()
        fresh.post(f"/api/table/rooms/{second['code']}/join", json={"name": "Ada again"})

        s = fresh.get("/api/account/stats").json()
        assert s["tables"] == 2
        assert s["games"] >= 2
        assert set(s["byMode"]) == {"life", "treachery"}
        assert s["firstAt"] is not None and s["lastAt"] >= s["firstAt"]
        assert first["code"] != second["code"]

    def test_counts_notes(self, fresh):
        signup(fresh, "stats.notes")
        room = fresh.post("/api/table/rooms", json={"name": "Ada", "mode": "life"}).json()
        fresh.put(f"/api/account/notes/{room['code']}/0", json={"text": "went long"})
        assert fresh.get("/api/account/stats").json()["notes"] == 1

    def test_counts_the_whole_history_not_one_page(self, fresh):
        """The point of a separate endpoint: /history is paged, totals are not."""
        signup(fresh, "stats.deep")
        for _ in range(4):
            fresh.post("/api/table/rooms", json={"name": "Ada", "mode": "life"})
        assert fresh.get("/api/account/history?limit=2").json()["games"].__len__() == 2
        assert fresh.get("/api/account/stats").json()["games"] == 4

    def test_another_account_sees_none_of_it(self, fresh):
        signup(fresh, "stats.mine")
        fresh.post("/api/table/rooms", json={"name": "Ada", "mode": "life"})
        fresh.cookies.clear()
        signup(fresh, "stats.theirs")
        assert fresh.get("/api/account/stats").json()["games"] == 0

    def test_signed_out_callers_are_refused(self, fresh):
        assert fresh.get("/api/account/stats").status_code == 401
