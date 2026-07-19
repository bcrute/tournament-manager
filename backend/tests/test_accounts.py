"""Optional accounts: signup, login, recovery without email, history, notes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import hash_password, router as accounts_router, verify_password
from app.table import router as table_router


@pytest.fixture(scope="module")
def app_client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    # https base URL: the session cookie is Secure, so a client on http would
    # (correctly) refuse to store it
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def fresh(app_client):
    """A signed-out client. TestClient keeps cookies, so clear between tests."""
    app_client.cookies.clear()
    return app_client


def signup(c, username, password="correct horse battery"):
    return c.post("/api/account/signup", json={"username": username, "password": password})


class TestPasswordHashing:
    def test_round_trip(self):
        stored = hash_password("hunter2 hunter2")
        assert verify_password("hunter2 hunter2", stored)
        assert not verify_password("something else", stored)

    def test_hash_is_salted(self):
        assert hash_password("same password") != hash_password("same password")

    def test_plaintext_never_appears(self):
        assert "hunter2" not in hash_password("hunter2 hunter2")

    def test_garbage_stored_value_fails_closed(self):
        assert not verify_password("x", "not-a-hash")
        assert not verify_password("x", "bcrypt$abc$def")


class TestSignup:
    def test_creates_account_and_signs_in(self, fresh):
        r = signup(fresh, "alice")
        assert r.status_code == 200
        body = r.json()
        assert body["account"]["username"] == "alice"
        assert body["account"]["hasEmail"] is False
        assert fresh.get("/api/account/me").json()["account"]["username"] == "alice"

    def test_issues_one_time_recovery_codes(self, fresh):
        codes = signup(fresh, "bob").json()["recoveryCodes"]
        assert len(codes) == 8 and len(set(codes)) == 8

    def test_no_email_required(self, fresh):
        assert signup(fresh, "carol").json()["account"]["hasEmail"] is False

    def test_username_taken(self, fresh):
        signup(fresh, "dave")
        fresh.cookies.clear()
        assert signup(fresh, "dave").status_code == 409

    def test_username_is_case_insensitive_for_uniqueness(self, fresh):
        signup(fresh, "Erin")
        fresh.cookies.clear()
        assert signup(fresh, "erin").status_code == 409

    def test_rejects_bad_usernames(self, fresh):
        # the limit is 64 so an email address fits; `@` and `+` are allowed
        for bad in ("ab", "has space", "emoji🙂", "x" * 65, "semi;colon"):
            assert signup(fresh, bad).status_code in (400, 422), bad

    def test_rejects_short_passwords(self, fresh):
        assert signup(fresh, "shorty", "abc").status_code == 422


class TestLogin:
    def test_login_and_logout(self, fresh):
        signup(fresh, "frank")
        fresh.cookies.clear()
        assert fresh.get("/api/account/me").json()["account"] is None
        r = fresh.post(
            "/api/account/login", json={"username": "frank", "password": "correct horse battery"}
        )
        assert r.status_code == 200
        assert fresh.get("/api/account/me").json()["account"]["username"] == "frank"
        fresh.post("/api/account/logout")
        assert fresh.get("/api/account/me").json()["account"] is None

    def test_wrong_password_rejected(self, fresh):
        signup(fresh, "grace")
        fresh.cookies.clear()
        r = fresh.post("/api/account/login", json={"username": "grace", "password": "wrong pass!!"})
        assert r.status_code == 401

    def test_unknown_user_gives_the_same_error(self, fresh):
        """Don't leak which usernames exist."""
        a = fresh.post("/api/account/login", json={"username": "nobody-here", "password": "whatever!"})
        signup(fresh, "heidi")
        fresh.cookies.clear()
        b = fresh.post("/api/account/login", json={"username": "heidi", "password": "wrongwrong"})
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]

    def test_session_cookie_is_httponly(self, fresh):
        r = signup(fresh, "ivan")
        assert "httponly" in r.headers["set-cookie"].lower()


class TestRecovery:
    def test_recover_with_a_code_no_email_needed(self, fresh):
        codes = signup(fresh, "judy").json()["recoveryCodes"]
        fresh.cookies.clear()
        r = fresh.post(
            "/api/account/recover",
            json={"username": "judy", "code": codes[0], "new_password": "brand new secret"},
        )
        assert r.status_code == 200
        fresh.cookies.clear()
        assert fresh.post(
            "/api/account/login", json={"username": "judy", "password": "brand new secret"}
        ).status_code == 200

    def test_a_code_only_works_once(self, fresh):
        codes = signup(fresh, "karl").json()["recoveryCodes"]
        fresh.cookies.clear()
        fresh.post(
            "/api/account/recover",
            json={"username": "karl", "code": codes[0], "new_password": "first change ok"},
        )
        r = fresh.post(
            "/api/account/recover",
            json={"username": "karl", "code": codes[0], "new_password": "second change no"},
        )
        assert r.status_code == 401

    def test_bad_code_rejected(self, fresh):
        signup(fresh, "lena")
        fresh.cookies.clear()
        r = fresh.post(
            "/api/account/recover",
            json={"username": "lena", "code": "dead-beef-cafe", "new_password": "nope nope nope"},
        )
        assert r.status_code == 401

    def test_changing_password_logs_other_devices_out(self, fresh, app_client):
        signup(fresh, "mike")
        r = fresh.post(
            "/api/account/password",
            json={"current": "correct horse battery", "new": "a different secret"},
        )
        assert r.status_code == 200
        # the cookie held by this client was invalidated with the rest
        assert fresh.get("/api/account/me").json()["account"] is None


class TestEmailOptional:
    def test_email_can_be_added_and_removed(self, fresh):
        signup(fresh, "nina")
        assert fresh.post("/api/account/email", json={"email": "nina@example.com"}).json()["hasEmail"]
        assert fresh.get("/api/account/me").json()["account"]["hasEmail"] is True
        assert fresh.post("/api/account/email", json={"email": None}).json()["hasEmail"] is False

    def test_obvious_junk_rejected(self, fresh):
        signup(fresh, "omar")
        assert fresh.post("/api/account/email", json={"email": "nope"}).status_code == 400


class TestSeatLinking:
    def test_games_played_signed_in_appear_in_history(self, fresh):
        signup(fresh, "pia")
        r = fresh.post("/api/table/rooms", json={"name": "pia", "mode": "life"})
        code = r.json()["code"]
        games = fresh.get("/api/account/history").json()["games"]
        assert any(g["roomCode"] == code and g["playedAs"] == "pia" for g in games)

    def test_anonymous_games_are_not_linked(self, fresh, app_client):
        signup(fresh, "quinn")
        before = len(fresh.get("/api/account/history").json()["games"])
        app_client.cookies.clear()  # play signed out
        app_client.post("/api/table/rooms", json={"name": "ghost", "mode": "life"})
        fresh.post("/api/account/login", json={"username": "quinn", "password": "correct horse battery"})
        assert len(fresh.get("/api/account/history").json()["games"]) == before

    def test_history_requires_sign_in(self, fresh):
        fresh.cookies.clear()
        assert fresh.get("/api/account/history").status_code == 401


class TestNotes:
    def test_write_read_update_and_clear(self, fresh):
        signup(fresh, "rosa")
        code = fresh.post("/api/table/rooms", json={"name": "rosa", "mode": "life"}).json()["code"]
        assert fresh.get(f"/api/account/notes/{code}/1").json()["text"] == ""
        fresh.put(f"/api/account/notes/{code}/1", json={"text": "won on turn 7"})
        assert fresh.get(f"/api/account/notes/{code}/1").json()["text"] == "won on turn 7"
        fresh.put(f"/api/account/notes/{code}/1", json={"text": "actually turn 8"})
        assert fresh.get(f"/api/account/notes/{code}/1").json()["text"] == "actually turn 8"
        fresh.put(f"/api/account/notes/{code}/1", json={"text": "   "})
        assert fresh.get(f"/api/account/notes/{code}/1").json()["text"] == ""

    def test_notes_are_private_to_their_author(self, fresh, app_client):
        signup(fresh, "sven")
        code = fresh.post("/api/table/rooms", json={"name": "sven", "mode": "life"}).json()["code"]
        fresh.put(f"/api/account/notes/{code}/1", json={"text": "my secret read"})
        app_client.cookies.clear()
        signup(app_client, "tara")
        assert app_client.get(f"/api/account/notes/{code}/1").json()["text"] == ""
        assert app_client.get("/api/account/notes").json()["notes"] == []

    def test_notes_require_sign_in(self, fresh):
        fresh.cookies.clear()
        assert fresh.get("/api/account/notes").status_code == 401
        assert fresh.put("/api/account/notes/ABCDE/1", json={"text": "x"}).status_code == 401

    def test_notes_are_listed_for_the_dashboard(self, fresh):
        signup(fresh, "umar")
        code = fresh.post("/api/table/rooms", json={"name": "umar", "mode": "life"}).json()["code"]
        fresh.put(f"/api/account/notes/{code}/2", json={"text": "pod was brutal"})
        notes = fresh.get("/api/account/notes").json()["notes"]
        assert any(n["roomCode"] == code and n["gameNo"] == 2 for n in notes)


class TestHistoryNotesLink:
    def test_note_for_the_current_game_shows_in_history(self, fresh):
        """Regression: notes were keyed to a clamped game number while history
        looked up the room's real one, so saved notes never appeared."""
        signup(fresh, "vera")
        room = fresh.post("/api/table/rooms", json={"name": "vera", "mode": "life"}).json()
        code, token = room["code"], room["playerToken"]
        state = fresh.get(f"/api/table/rooms/{code}/me", headers={"X-Player-Token": token}).json()
        game_no = state["room"]["gameNo"]  # 0 while still in the lobby
        fresh.put(f"/api/account/notes/{code}/{game_no}", json={"text": "pre-game thoughts"})
        game = next(g for g in fresh.get("/api/account/history").json()["games"] if g["roomCode"] == code)
        assert game["note"] == "pre-game thoughts"

    def test_note_follows_the_game_number_after_a_deal(self, fresh):
        signup(fresh, "wes")
        room = fresh.post("/api/table/rooms", json={"name": "wes", "mode": "life"}).json()
        code, token = room["code"], room["playerToken"]
        hdr = {"X-Player-Token": token}
        fresh.post(f"/api/table/rooms/{code}/start", headers=hdr)
        after = fresh.get(f"/api/table/rooms/{code}/me", headers=hdr).json()["room"]["gameNo"]
        assert after == 1
        fresh.put(f"/api/account/notes/{code}/{after}", json={"text": "game one"})
        game = next(g for g in fresh.get("/api/account/history").json()["games"] if g["roomCode"] == code)
        assert game["note"] == "game one"

    def test_a_note_from_a_different_game_does_not_bleed_in(self, fresh):
        signup(fresh, "xena")
        room = fresh.post("/api/table/rooms", json={"name": "xena", "mode": "life"}).json()
        code, token = room["code"], room["playerToken"]
        hdr = {"X-Player-Token": token}
        fresh.put(f"/api/account/notes/{code}/0", json={"text": "lobby note"})
        fresh.post(f"/api/table/rooms/{code}/start", headers=hdr)
        game = next(g for g in fresh.get("/api/account/history").json()["games"] if g["roomCode"] == code)
        assert game["note"] is None  # room is on game 1 now; the game 0 note stays put


class TestAccountDeletion:
    def test_delete_removes_account_notes_and_sessions(self, fresh):
        signup(fresh, "yuri")
        code = fresh.post("/api/table/rooms", json={"name": "yuri", "mode": "life"}).json()["code"]
        fresh.put(f"/api/account/notes/{code}/0", json={"text": "gone soon"})
        assert fresh.post("/api/account/delete", json={"confirm": "yuri"}).status_code == 200
        # session is dead and the username is free again
        assert fresh.get("/api/account/me").json()["account"] is None
        assert signup(fresh, "yuri").status_code == 200
        # the fresh account of the same name inherits nothing
        assert fresh.get(f"/api/account/notes/{code}/0").json()["text"] == ""
        assert fresh.get("/api/account/history").json()["games"] == []

    def test_confirmation_must_match_the_username(self, fresh):
        signup(fresh, "zane")
        assert fresh.post("/api/account/delete", json={"confirm": "wrong"}).status_code == 400
        assert fresh.post("/api/account/delete", json={"confirm": ""}).status_code == 400
        assert fresh.get("/api/account/me").json()["account"]["username"] == "zane"

    def test_confirmation_is_case_insensitive(self, fresh):
        signup(fresh, "amy")
        assert fresh.post("/api/account/delete", json={"confirm": "AMY"}).status_code == 200

    def test_requires_sign_in(self, fresh):
        fresh.cookies.clear()
        assert fresh.post("/api/account/delete", json={"confirm": "anyone"}).status_code == 401

    def test_games_survive_but_are_unlinked(self, fresh):
        """Other players keep their record of the table; the seat just stops
        pointing at a person."""
        from app.db import q

        signup(fresh, "bram")
        room = fresh.post("/api/table/rooms", json={"name": "bram", "mode": "life"}).json()
        code = room["code"]
        fresh.post("/api/account/delete", json={"confirm": "bram"})
        seat = q("SELECT name, account_id FROM players WHERE room_code = ?", (code,)).fetchone()
        assert seat["name"] == "bram"       # the table still shows what happened
        assert seat["account_id"] is None   # but nothing ties it to an account
        assert q("SELECT COUNT(*) c FROM rooms WHERE code = ?", (code,)).fetchone()["c"] == 1


class TestAuthTimingAndSessions:
    def test_login_costs_the_same_whether_or_not_the_account_exists(self, fresh):
        """Username enumeration by stopwatch: without constant work, a missing
        account returns in microseconds and a real one costs a full scrypt."""
        import time as _t
        fresh.post("/api/account/signup",
                    json={"username": "timingreal", "password": "a good long password"})

        def elapsed(username):
            best = 1e9
            for _ in range(3):   # take the minimum: least affected by noise
                s = _t.perf_counter()
                fresh.post("/api/account/login",
                            json={"username": username, "password": "wrong password here"})
                best = min(best, _t.perf_counter() - s)
            return best

        real, absent = elapsed("timingreal"), elapsed("timingnobody")
        # both should pay for a scrypt; allow generous slack for a noisy runner
        assert absent > real * 0.5, f"absent={absent:.3f}s real={real:.3f}s"

    def test_a_session_unused_past_the_idle_window_is_dead(self, fresh):
        from app.accounts import SESSION_IDLE_DAYS
        from app.db import q as dbq
        fresh.post("/api/account/signup",
                    json={"username": "idleuser", "password": "a good long password"})
        assert fresh.get("/api/account/me").json()["account"] is not None
        dbq("UPDATE sessions SET last_seen = last_seen - ?",
            ((SESSION_IDLE_DAYS + 1) * 86400,))
        assert fresh.get("/api/account/me").json()["account"] is None

    def test_using_a_session_keeps_it_alive(self, fresh):
        from app.db import q as dbq
        fresh.post("/api/account/signup",
                    json={"username": "activeuser", "password": "a good long password"})
        dbq("UPDATE sessions SET last_seen = last_seen - 86400")
        fresh.get("/api/account/me")     # a use must refresh it
        row = dbq("SELECT last_seen FROM sessions ORDER BY rowid DESC LIMIT 1").fetchone()
        import time as _t
        assert _t.time() - row["last_seen"] < 60


class TestSignupEmail:
    def test_an_email_is_optional_at_signup(self, fresh):
        r = signup(fresh, "noemailuser")
        assert r.status_code == 200
        assert r.json()["account"]["hasEmail"] is False

    def test_an_email_can_be_given_at_signup(self, fresh):
        r = fresh.post("/api/account/signup", json={
            "username": "withemailuser", "password": "correct horse battery",
            "email": "someone@example.com"})
        assert r.status_code == 200 and r.json()["account"]["hasEmail"] is True

    def test_the_address_itself_is_never_returned(self, fresh):
        import json as _json
        r = fresh.post("/api/account/signup", json={
            "username": "privateemail", "password": "correct horse battery",
            "email": "private@example.com"})
        assert "private@example.com" not in _json.dumps(r.json())
        assert "private@example.com" not in _json.dumps(fresh.get("/api/account/me").json())

    def test_a_nonsense_address_is_rejected(self, fresh):
        r = fresh.post("/api/account/signup", json={
            "username": "bademailuser", "password": "correct horse battery",
            "email": "nope"})
        assert r.status_code == 400

    def test_an_email_is_allowed_as_a_username(self, fresh):
        """Discouraged in the UI, never prevented. The user's call."""
        r = fresh.post("/api/account/signup", json={
            "username": "ben@example.com", "password": "correct horse battery"})
        assert r.status_code == 200
        assert r.json()["account"]["username"] == "ben@example.com"

    def test_an_email_shaped_username_is_not_written_to_the_security_log(self, fresh):
        """A typo at sign-in must not put someone's address in a log they can't
        see. The attempt is recorded; the address is not."""
        from app.db import q as dbq
        fresh.post("/api/account/login", json={
            "username": "nobody@example.com", "password": "wrong password here"})
        rows = dbq("SELECT subject FROM security_log WHERE kind = 'auth.unknown' "
                   "ORDER BY id DESC LIMIT 5").fetchall()
        subjects = [r["subject"] for r in rows]
        assert "<email-shaped>" in subjects
        assert not any(s and "@" in s for s in subjects)

    def test_recovery_codes_are_issued_whether_or_not_an_email_was_given(self, fresh):
        r = fresh.post("/api/account/signup", json={
            "username": "codesanyway", "password": "correct horse battery",
            "email": "codes@example.com"})
        assert len(r.json()["recoveryCodes"]) == 8
