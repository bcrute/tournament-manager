"""Three contract accuracy claims, pinned.

- §5's rate-limit classification is the code's suffix list, not a per-area rule.
- §6's recovery email is write-only: nothing reads the value, ever.
- §2's per-pod extension is added on *read*, in both read paths, and never
  mutates the round deadline.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.limits import classify
from app.table import router as table_router
from app.tournaments import router as tournaments_router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def organizer(client, username, email=None):
    client.cookies.clear()
    client.post("/api/account/signup", json={"username": username, "password": "a good long password"})
    client.post("/api/account/email", json={"email": email or f"{username}@example.com"})
    return client


def host(client, name="Friday Night", settings=None):
    r = client.post("/api/tournament", json={"name": name, "mode": "life",
                                             "settings": settings or {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


class TestRateLimitClassification:
    """§5: classification is method + path suffix and nothing else."""

    def test_account_writes_that_can_take_an_account_away_are_sensitive(self):
        # credential surfaces: stuffing and signup spam
        assert classify("/api/account/signup", "POST") == "sensitive"
        assert classify("/api/account/login", "POST") == "sensitive"
        assert classify("/api/account/recover", "POST") == "sensitive"
        assert classify("/api/account/password", "POST") == "sensitive"
        assert classify("/api/account/recovery-codes", "POST") == "sensitive"
        # takeover surfaces: the recovery address, and erasure
        assert classify("/api/account/email", "POST") == "sensitive"
        assert classify("/api/account/delete", "POST") == "sensitive"

    def test_session_gated_ordinary_account_traffic_stays_normal(self):
        """Not every account path is sensitive — logout and note-saving are
        ordinary traffic, and a note is saved as often as a player types."""
        assert classify("/api/account/logout", "POST") == "normal"
        assert classify("/api/account/notes/ABCDE/1", "PUT") == "normal"

    def test_every_get_is_normal(self):
        assert classify("/api/account/me", "GET") == "normal"
        assert classify("/api/account/history", "GET") == "normal"
        assert classify("/api/tournament/ABCDE", "GET") == "normal"
        assert classify("/api/tournament/ABCDE/roster", "GET") == "normal"

    def test_tournament_writes_that_hand_out_credentials_or_decide_games(self):
        """/claim hands out an entrant token; /entrants and /turn are writes a
        script should not get 900 of a minute. The contract lists these three
        explicitly — do not loosen one to make a sentence read better."""
        assert classify("/api/tournament/ABCDE/claim", "POST") == "sensitive"
        assert classify("/api/tournament/ABCDE/entrants", "POST") == "sensitive"
        assert classify("/api/tournament/ABCDE/pods/3/turn", "POST") == "sensitive"

    def test_ordinary_tournament_writes_are_normal(self):
        assert classify("/api/tournament/ABCDE/timer", "POST") == "normal"
        assert classify("/api/tournament/ABCDE/rounds", "POST") == "normal"
        assert classify("/api/tournament/ABCDE/rounds/close", "POST") == "normal"
        assert classify("/api/tournament/ABCDE/pods/3/result", "POST") == "normal"
        assert classify("/api/tournament/ABCDE/pods/3/call", "POST") == "normal"


class TestRecoveryEmailIsWriteOnly:
    """§6: stored, never returned, and read by nothing but a truthiness test."""

    def test_no_endpoint_ever_returns_the_address(self, client):
        addr = "hostmail-secret@example.com"
        organizer(client, "mailA", email=addr)
        code = host(client)
        add(client, code, ["m1", "m2", "m3", "m4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        bodies = [
            client.get("/api/account/me").text,
            client.get("/api/account/history").text,
            client.get("/api/account/notes").text,
            client.get("/api/tournament/mine").text,
            client.get(f"/api/tournament/{code}").text,
            client.get(f"/api/tournament/{code}/roster").text,
            client.get(f"/api/tournament/{code}/plan").text,
        ]
        for body in bodies:
            assert addr not in body
        assert client.get("/api/account/me").json()["account"]["hasEmail"] is True

    def test_recovery_does_not_use_the_address(self, client):
        """The claim in §6 is that the address is used *only* for recovery. The
        honest form is narrower: recovery is one-time-code only, so the address
        is not used at all. Pin that, so adding a mail path is a deliberate
        change and not an accident."""
        client.cookies.clear()
        r = client.post("/api/account/signup",
                        json={"username": "mailB", "password": "a good long password"})
        codes = r.json()["recoveryCodes"]
        client.post("/api/account/email", json={"email": "mailb@example.com"})
        client.cookies.clear()
        # no address is supplied anywhere in the recovery request
        rec = client.post("/api/account/recover",
                          json={"username": "mailB", "code": codes[0],
                                "new_password": "another good long password"})
        assert rec.status_code == 200, rec.text
        # and an account with no address recovers exactly the same way
        client.cookies.clear()
        r2 = client.post("/api/account/signup",
                         json={"username": "mailC", "password": "a good long password"})
        codes2 = r2.json()["recoveryCodes"]
        client.cookies.clear()
        rec2 = client.post("/api/account/recover",
                           json={"username": "mailC", "code": codes2[0],
                                 "new_password": "another good long password"})
        assert rec2.status_code == 200, rec2.text
        assert rec2.json()["account"]["hasEmail"] is False

    def test_the_server_sends_no_mail(self):
        """§10 says the recovery email recovers nothing yet. If that stops
        being true this test should fail and the gap note should go."""
        import pathlib

        app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
        source = "\n".join(p.read_text() for p in app_dir.glob("*.py"))
        for marker in ("smtplib", "sendmail", "send_mail", "send_email"):
            assert marker not in source


class TestExtensionIsAddedOnRead:
    """§2: a pod's extension moves that pod's deadline on read only."""

    def _started_event(self, client, username, entrants=8):
        organizer(client, username)
        code = host(client, settings={"roundMinutes": 50})
        add(client, code, [f"{username}{i}" for i in range(entrants)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/timer", json={"action": "start", "minutes": 50})
        return code

    def test_pod_ends_at_carries_the_extension(self, client):
        code = self._started_event(client, "extA")
        before = client.get(f"/api/tournament/{code}").json()
        pods = before["pods"]
        client.post(f"/api/tournament/{code}/timer",
                    json={"action": "extend", "minutes": 10, "podId": pods[0]["podId"]})
        after = client.get(f"/api/tournament/{code}").json()

        # the round's own deadline is untouched — the extension is not stored there
        assert after["round"]["endsAt"] == before["round"]["endsAt"]
        assert after["pods"][0]["extensionSeconds"] == 600
        assert after["pods"][0]["endsAt"] == after["round"]["endsAt"] + 600
        # and only that table moved
        for pod in after["pods"][1:]:
            assert pod["extensionSeconds"] == 0
            assert pod["endsAt"] == after["round"]["endsAt"]

    def test_extensions_accumulate_on_read(self, client):
        code = self._started_event(client, "extB", entrants=4)
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        for _ in range(2):
            client.post(f"/api/tournament/{code}/timer",
                        json={"action": "extend", "minutes": 5, "podId": pod["podId"]})
        state = client.get(f"/api/tournament/{code}").json()
        assert state["pods"][0]["endsAt"] == state["round"]["endsAt"] + 600

    def test_a_player_sees_the_same_deadline_on_both_pages(self, client):
        """The room view and the tournament view are the same clock. They
        disagreed before: the tournament page ignored the extension."""
        code = self._started_event(client, "extC", entrants=4)
        added = client.get(f"/api/tournament/{code}/roster").json()["entrants"]
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(f"/api/tournament/{code}/timer",
                    json={"action": "extend", "minutes": 15, "podId": pod["podId"]})
        client.cookies.clear()
        tok = client.post(f"/api/tournament/{code}/claim",
                          json={"entrantId": added[0]["entrantId"]}).json()["entrantToken"]
        my = client.get(f"/api/tournament/{code}", params={"token": tok}).json()["myPod"]
        room = client.get(f"/api/table/rooms/{my['roomCode']}/me",
                          headers={"X-Player-Token": my["roomToken"]}).json()
        assert my["endsAt"] == room["tournament"]["endsAt"]

    def test_no_timer_means_no_pod_deadline(self, client):
        organizer(client, "extD")
        code = host(client)
        add(client, code, ["d1", "d2", "d3", "d4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        state = client.get(f"/api/tournament/{code}").json()
        assert state["round"]["endsAt"] is None
        assert state["pods"][0]["endsAt"] is None
