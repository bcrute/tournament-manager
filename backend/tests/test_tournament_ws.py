"""Tournament WebSocket: event-wide changes push, and push per viewer.

The room socket carries what happens inside one pod. This one carries what
happens to the event — pairings, results, standings, the roster, the calls
queue — which until now only arrived on the next poll.

The rules it must not break are §1's: a room code is organizer-only, and a room
token belongs to exactly one seat. A fanout is the easiest place in the app to
lose that, because one snapshot goes to everybody at once, so most of what is
below is aimed straight at it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
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


def organizer(client, username):
    client.cookies.clear()
    client.post(
        "/api/account/signup", json={"username": username, "password": "a good long password"}
    )
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, name="Friday Night", settings=None):
    r = client.post("/api/tournament", json={"name": name, "settings": settings or {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def socket(client, code):
    """Open the tournament socket the way a browser does.

    The absolute `wss://` URL is deliberate: TestClient hardcodes `ws://`, and
    the session cookie is `secure`, so a relative path would silently drop the
    organizer's credential and every organizer test would pass for the wrong
    reason. In production the page is https and the socket is same-origin wss.
    """
    return client.websocket_connect(f"wss://testserver/api/tournament/ws/{code}")


def claim(client, code, entrant_id):
    return client.post(
        f"/api/tournament/{code}/claim", json={"entrantId": entrant_id}
    ).json()["entrantToken"]


def seats_of(pod_id):
    return q(
        "SELECT s.entrant_id, s.room_token, s.seat, e.public_id FROM pod_seats s "
        "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
        (pod_id,),
    ).fetchall()


class TestTournamentSocket:
    def test_state_arrives_on_connect(self, client):
        """A phone that connects mid-round should not have to wait for somebody
        else to change something before it knows where it stands."""
        organizer(client, "wsA")
        code = host(client)
        add(client, code, ["a1", "a2", "a3", "a4"])
        with socket(client, code) as ws:
            first = ws.receive_json()
            assert first["type"] == "state"
            assert first["state"]["tournament"]["code"] == code
            assert len(first["state"]["standings"]) == 4

    def test_a_change_pushes_without_a_poll(self, client):
        """The whole point: pairings reach the table when they are made."""
        organizer(client, "wsB")
        code = host(client)
        add(client, code, ["b1", "b2", "b3", "b4"])
        with socket(client, code) as ws:
            ws.receive_json()  # opening state, no round yet
            client.post(f"/api/tournament/{code}/rounds", json={})
            pushed = ws.receive_json()
            assert pushed["type"] == "state"
            assert pushed["state"]["round"]["number"] == 1
            assert len(pushed["state"]["pods"]) == 1

    def test_the_poll_still_answers_while_a_socket_is_open(self, client):
        """The socket is an addition. A client whose socket drops must degrade
        to a slower view, never to a stuck one."""
        organizer(client, "wsC")
        code = host(client)
        add(client, code, ["c1", "c2", "c3", "c4"])
        with socket(client, code) as ws:
            ws.receive_json()
            client.post(f"/api/tournament/{code}/rounds", json={})
            pushed = ws.receive_json()["state"]
        polled = client.get(f"/api/tournament/{code}").json()
        assert polled["pods"][0]["podId"] == pushed["pods"][0]["podId"]
        assert polled["isOrganizer"] is pushed["isOrganizer"]

    def test_an_entrant_only_ever_gets_their_own_seats_room_token(self, client):
        """Two players at one table, one snapshot, two different views. A room
        token is a seat credential — the other seat's must never appear."""
        organizer(client, "wsD")
        code = host(client)
        added = add(client, code, ["d1", "d2", "d3", "d4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        t1 = claim(client, code, added[0]["entrantId"])
        t2 = claim(client, code, added[1]["entrantId"])
        with socket(client, code) as a, socket(client, code) as b:
            a.receive_json()
            b.receive_json()
            a.send_json({"token": t1})
            b.send_json({"token": t2})
            sa, sb = a.receive_json()["state"], b.receive_json()["state"]
            assert sa["me"]["name"] == "d1" and sb["me"]["name"] == "d2"
            assert sa["myPod"]["roomToken"] and sb["myPod"]["roomToken"]
            assert sa["myPod"]["roomToken"] != sb["myPod"]["roomToken"]
            assert sa["myPod"]["mySeat"] != sb["myPod"]["mySeat"]
            # and nobody's token rides along in the pod list everyone can read
            for state in (sa, sb):
                for pod in state["pods"]:
                    assert "roomToken" not in pod
                    for seat in pod["seats"]:
                        assert "roomToken" not in seat and "room_token" not in seat

    def test_a_pushed_change_keeps_each_socket_personalized(self, client):
        """Personalization must hold on every push, not only on the first."""
        organizer(client, "wsE")
        code = host(client)
        added = add(client, code, ["e1", "e2", "e3", "e4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        t1 = claim(client, code, added[0]["entrantId"])
        with socket(client, code) as mine, socket(client, code) as anon:
            mine.receive_json()
            anon.receive_json()
            mine.send_json({"token": t1})
            mine.receive_json()
            claim(client, code, added[1]["entrantId"])   # somebody else checks in
            pushed_mine = mine.receive_json()["state"]
            pushed_anon = anon.receive_json()["state"]
            assert pushed_mine["me"]["name"] == "e1"
            assert pushed_mine["myPod"]["roomToken"]
            # the anonymous socket saw the same event and none of the credential
            assert pushed_anon["me"] is None and pushed_anon["myPod"] is None
            assert all(p["roomCode"] is None for p in pushed_anon["pods"])

    def test_room_codes_stay_organizer_only(self, client):
        """A room code lets its holder take a seat in that room. The organizer
        gets every one; an entrant gets their own table's and no other."""
        organizer(client, "wsF")
        code = host(client)
        added = add(client, code, ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        with socket(client, code) as org:
            org_state = org.receive_json()["state"]
        assert org_state["isOrganizer"] is True
        assert len(org_state["pods"]) == 2
        assert all(p["roomCode"] for p in org_state["pods"])

        client.cookies.clear()
        token = claim(client, code, added[0]["entrantId"])
        with socket(client, code) as ws:
            ws.receive_json()
            ws.send_json({"token": token})
            state = ws.receive_json()["state"]
        assert state["isOrganizer"] is False
        assert all(p["roomCode"] is None for p in state["pods"])
        assert state["myPod"]["roomCode"]   # their own table, so they get it

    def test_players_never_receive_the_calls_queue(self, client):
        organizer(client, "wsG")
        code = host(client)
        added = add(client, code, ["g1", "g2", "g3", "g4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        org_cookies = dict(client.cookies)
        client.cookies.clear()
        token = claim(client, code, added[0]["entrantId"])
        with socket(client, code) as player:
            player.receive_json()
            player.send_json({"token": token})
            player.receive_json()
            client.cookies.update(org_cookies)
            with socket(client, code) as org:
                org.receive_json()
                client.cookies.clear()
                client.post(
                    f"/api/tournament/{code}/pods/{pod['podId']}/call",
                    params={"token": token},
                    json={"category": "rules"},
                )
                assert len(org.receive_json()["state"]["calls"]) == 1
            assert player.receive_json()["state"]["calls"] == []

    def test_a_socket_does_not_outlive_the_session_that_authorized_it(self, client):
        """An organizer view is bound to a session, not to a connection. Sign
        the session out from under a socket left open all day and the next push
        is an ordinary viewer's."""
        organizer(client, "wsH")
        code = host(client)
        added = add(client, code, ["h1", "h2", "h3", "h4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        with socket(client, code) as ws:
            assert ws.receive_json()["state"]["isOrganizer"] is True
            q(
                "DELETE FROM sessions WHERE account_id = "
                "(SELECT id FROM accounts WHERE username = ?)",
                ("wsH",),
            )
            # a public action, so the push happens even though the organizer
            # can no longer do anything themselves
            client.cookies.clear()
            claim(client, code, added[0]["entrantId"])
            state = ws.receive_json()["state"]
            assert state["isOrganizer"] is False
            assert all(p["roomCode"] is None for p in state["pods"])

    def test_an_auto_result_from_the_pod_room_pushes_new_standings(self, client):
        """The result path that runs itself: a game ending in the room moves the
        standings, and the board should not wait for a poll to say so."""
        organizer(client, "wsI")
        code = host(client)
        add(client, code, ["i1", "i2", "i3", "i4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        seats = seats_of(pod["podId"])
        room = pod["roomCode"]
        client.post(
            f"/api/table/rooms/{room}/start", headers={"X-Player-Token": seats[0]["room_token"]}
        )
        with socket(client, code) as ws:
            ws.receive_json()
            for s in seats[1:]:
                client.post(
                    f"/api/table/rooms/{room}/eliminate",
                    headers={"X-Player-Token": s["room_token"]},
                    json={},
                )
            # only the last elimination ends the game, so only it records a
            # result — the pushes before it belong to the room, not here
            state = ws.receive_json()["state"]
        assert state["standings"][0]["entrantId"] == seats[0]["public_id"]
        assert state["standings"][0]["points"] == 3
        assert state["pods"][0]["status"] == "complete"

    def test_the_round_clock_reaches_the_tournament_view_too(self, client):
        """Clock pushes already reach the pod rooms. The tournament view runs
        the same countdown and needs the same push."""
        organizer(client, "wsJ")
        code = host(client)
        add(client, code, ["j1", "j2", "j3", "j4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        with socket(client, code) as ws:
            assert ws.receive_json()["state"]["round"]["endsAt"] is None
            client.post(f"/api/tournament/{code}/timer", json={"action": "start", "minutes": 50})
            state = ws.receive_json()["state"]
            assert state["round"]["endsAt"] > state["round"]["now"]
            client.post(f"/api/tournament/{code}/timer", json={"action": "pause"})
            assert ws.receive_json()["state"]["round"]["pausedAt"] is not None

    def test_another_tournaments_socket_is_not_notified(self, client):
        organizer(client, "wsK")
        code1 = host(client, "one")
        code2 = host(client, "two")
        add(client, code1, ["k1", "k2", "k3", "k4"])
        add(client, code2, ["k5", "k6", "k7", "k8"])
        with socket(client, code1) as ws1, socket(client, code2) as ws2:
            ws1.receive_json()
            ws2.receive_json()
            client.post(f"/api/tournament/{code2}/rounds", json={})
            assert ws2.receive_json()["state"]["round"]["number"] == 1
            # ws1 got nothing from that: the next thing it receives is its own
            client.post(f"/api/tournament/{code1}/rounds", json={})
            assert ws1.receive_json()["state"]["tournament"]["code"] == code1

    def test_keepalives_and_junk_do_not_kill_the_socket(self, client):
        organizer(client, "wsL")
        code = host(client)
        add(client, code, ["l1", "l2", "l3", "l4"])
        with socket(client, code) as ws:
            ws.receive_json()
            ws.send_text("ping")            # keepalive
            ws.send_json({"hello": "there"})  # no token: ignored, not fatal
            client.post(f"/api/tournament/{code}/rounds", json={})
            assert ws.receive_json()["state"]["round"]["number"] == 1

    def test_an_unknown_code_gets_a_nudge_rather_than_a_guess(self, client):
        """Nothing to say, so say nothing but 'refetch' — the client's own GET
        will see the 404 and can act on it."""
        organizer(client, "wsM")
        with socket(client, "ZZZZZ") as ws:
            assert ws.receive_json() == {"type": "update"}

    def test_a_dropped_socket_is_forgotten(self, client):
        """A closed socket must not keep the tournament in the fanout table, or
        every event of the day leaks a registration."""
        from app.tournaments import _ws_viewers

        organizer(client, "wsN")
        code = host(client)
        add(client, code, ["n1", "n2"])
        with socket(client, code) as ws:
            ws.receive_json()
            assert len(_ws_viewers.get(code, {})) == 1
        client.post(f"/api/tournament/{code}/entrants", json={"names": ["n3"]})
        assert code not in _ws_viewers
