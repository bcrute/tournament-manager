"""What opens a room, and what merely names one.

`rooms.url_id` is 128 bits and is the only thing that lets an unauthenticated
caller into a room. `rooms.code` is five characters — short because someone
reads it across a table, and therefore short enough to walk — and now opens
nothing at all.

These tests are the boundary itself: every anonymous door, tried with the code,
must refuse. A door added later that forgets this is what they exist to catch.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.table import router as table_router
from app.tournaments import router as tournaments_router
from conftest import public_id


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def make_room(client, name="host"):
    return client.post("/api/table/rooms", json={"name": name, "mode": "life"}).json()


#: Every unauthenticated route that takes a room identifier. If a new one is
#: added, it belongs here — that is the point of the list being explicit.
ANONYMOUS_DOORS = [
    ("/api/table/rooms/join", lambda rid: {"roomId": rid, "name": "intruder", "display": False}),
    ("/api/table/rooms/seats", lambda rid: {"roomId": rid}),
    ("/api/table/rooms/reclaim", lambda rid: {"roomId": rid, "pid": 1, "force": False}),
]


class TestTheCodeOpensNothing:
    @pytest.mark.parametrize("path,body", ANONYMOUS_DOORS)
    def test_no_anonymous_route_accepts_the_five_character_code(self, client, path, body):
        made = make_room(client)
        r = client.post(path, json=body(made["code"]))
        assert r.status_code == 404, f"{path} let the internal code through"

    @pytest.mark.parametrize("path,body", ANONYMOUS_DOORS)
    def test_and_the_lowercase_code_is_no_better(self, client, path, body):
        made = make_room(client)
        r = client.post(path, json=body(made["code"].lower()))
        assert r.status_code == 404

    def test_the_public_id_does_open_them(self, client):
        """The other half: refusing everything would also pass the tests above."""
        made = make_room(client)
        assert client.post(
            "/api/table/rooms/join",
            json={"roomId": made["urlId"], "name": "guest", "display": False},
        ).status_code == 200
        assert client.post(
            "/api/table/rooms/seats", json={"roomId": made["urlId"]}
        ).status_code == 200

    def test_an_unknown_identifier_and_a_wrong_one_look_the_same(self, client):
        """No existence oracle: a real room's internal code must not be
        distinguishable from a string that was never a room at all."""
        made = make_room(client)
        real_code = client.post(
            "/api/table/rooms/seats", json={"roomId": made["code"]}
        )
        never_existed = client.post(
            "/api/table/rooms/seats", json={"roomId": "notARoomAtAllxxxxxxxxx"}
        )
        assert real_code.status_code == never_existed.status_code == 404
        assert real_code.json() == never_existed.json()


class TestIdentifierQuality:
    def test_every_room_gets_a_high_entropy_public_id(self, client):
        made = [make_room(client) for _ in range(5)]
        ids = {m["urlId"] for m in made}
        assert len(ids) == 5, "ids must be unique"
        for value in ids:
            assert len(value) >= 20, value
            # base64url, so a case fold would destroy it
            assert value == value.strip()

    def test_generation_retries_past_a_collision_instead_of_500ing(self, client, monkeypatch):
        """A duplicate used to reach the unique index and surface as a 500."""
        from app import table as table_mod

        taken = make_room(client)["urlId"]
        seq = iter([taken, taken, "afterTheCollisionXXXXX"])
        monkeypatch.setattr(table_mod.secrets, "token_urlsafe", lambda n: next(seq))

        r = client.post("/api/table/rooms", json={"name": "host", "mode": "life"})
        assert r.status_code == 200
        assert r.json()["urlId"] == "afterTheCollisionXXXXX"

    def test_the_code_and_the_public_id_are_different_things(self, client):
        made = make_room(client)
        assert made["urlId"] != made["code"]
        assert len(made["code"]) == 5


class TestTournamentPodHandoff:
    """A seated entrant never joins — they arrive with a pre-issued token — but
    their phone still has to reach the room, and it must do that by the public
    id rather than the code."""

    def organizer(self, client, username):
        client.cookies.clear()
        client.post("/api/account/signup",
                    json={"username": username, "password": "correct horse battery"})
        client.post("/api/account/email", json={"email": f"{username}@example.com"})

    def seated_event(self, client, username):
        """An open round with the viewer seated in it — claim after the pods
        exist, the way a player at the table actually does it."""
        self.organizer(client, username)
        code = client.post("/api/tournament", json={"name": "Pod Night"}).json()["code"]
        r = client.post(f"/api/tournament/{code}/entrants",
                        json={"names": ["Ada", "Bram", "Cleo", "Dev"]})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 200, r.text
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        assert pods, "a round with four entrants should have seated a pod"
        seat = pods[0]["seats"][0]
        claimed = client.post(f"/api/tournament/{code}/claim",
                              json={"entrantId": seat["entrantId"]})
        assert claimed.status_code == 200, claimed.text
        return code, claimed.json()["entrantToken"]

    def test_the_seated_entrant_is_given_the_rooms_public_id(self, client):
        code, token = self.seated_event(client, "podorg1")
        mine = client.get(f"/api/tournament/{code}", params={"token": token}).json()["myPod"]
        assert mine is not None
        assert mine["roomUrlId"], "an entrant cannot reach their table without it"
        row = q("SELECT url_id FROM rooms WHERE code = ?", (mine["roomCode"],)).fetchone()
        assert mine["roomUrlId"] == row["url_id"]

    def test_the_public_id_is_not_published_to_the_whole_field(self, client):
        """It opens a table. Everyone can see a pod exists; not everyone may
        walk into it."""
        code, token = self.seated_event(client, "podorg2")
        pods = client.get(f"/api/tournament/{code}", params={"token": token}).json()["pods"]
        assert pods
        assert all(p["roomUrlId"] is None for p in pods)

    def test_nor_to_an_anonymous_viewer(self, client):
        code, _ = self.seated_event(client, "podorg3")
        client.cookies.clear()
        snap = client.get(f"/api/tournament/{code}").json()
        assert all(p["roomUrlId"] is None for p in snap["pods"])
        assert all(p["roomCode"] is None for p in snap["pods"])

    def test_a_pod_room_cannot_be_joined_with_its_code(self, client):
        """The tournament path mints rooms of its own — they get the same
        boundary as any other room, not a quieter one."""
        code, token = self.seated_event(client, "podorg4")
        mine = client.get(f"/api/tournament/{code}", params={"token": token}).json()["myPod"]
        r = client.post("/api/table/rooms/join",
                        json={"roomId": mine["roomCode"], "name": "gatecrasher", "display": False})
        assert r.status_code == 404

    def test_but_the_organizer_still_sees_the_code_as_a_label(self, client):
        code, _ = self.seated_event(client, "podorg5")
        pods = client.get(f"/api/tournament/{code}").json()  # organizer cookie is set
        assert any(p["roomCode"] for p in pods["pods"])


class TestAlreadyJoinedSessionsSurvive:
    def test_an_authenticated_route_still_keys_on_the_internal_code(self, client):
        """A session held before this change carries the code and a player
        token. Those must keep working — the code is not a secret, it just
        isn't a credential on its own."""
        made = make_room(client)
        r = client.get(f"/api/table/rooms/{made['code']}/me",
                       headers={"X-Player-Token": made["playerToken"]})
        assert r.status_code == 200
        assert r.json()["room"]["urlId"] == made["urlId"]

    def test_but_the_code_alone_opens_nothing(self, client):
        made = make_room(client)
        assert client.get(f"/api/table/rooms/{made['code']}/me").status_code == 401
        assert client.get(f"/api/table/rooms/{made['code']}/me",
                          headers={"X-Player-Token": "not-a-token"}).status_code == 403
