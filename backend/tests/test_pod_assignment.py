"""The organizer's override over the pairer: moving an entrant between pods,
setting turn order at a table, and naming a table.

The interesting part is not the row that changes — it is everything hanging off
it. A pod is backed by a real room, so a move retires one room token and issues
another; `met_history` and standings are derived from `pod_seats`, so a move
before a result needs no repair and a move after one is refused outright.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.table import router as table_router
from app.tournaments import met_history
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
    client.post("/api/account/signup", json={"username": username, "password": "a good long password"})
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, name="Move Night", settings=None):
    r = client.post("/api/tournament", json={"name": name, "settings": settings or {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def event(client, username, players=12, settings=None):
    """An open round over `players` entrants: (code, pods)."""
    organizer(client, username)
    code = host(client, settings=settings)
    add(client, code, [f"{username}-{i}" for i in range(players)])
    assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
    return code, client.get(f"/api/tournament/{code}").json()["pods"]


def pods_of(client, code):
    return client.get(f"/api/tournament/{code}").json()["pods"]


def move(client, code, pod_id, entrant_id):
    return client.post(f"/api/tournament/{code}/pods/{pod_id}/move", json={"entrantId": entrant_id})


def members(pod):
    return {s["entrantId"] for s in pod["seats"]}


class TestMovingAnEntrant:
    def test_the_entrant_changes_table(self, client):
        code, pods = event(client, "moveA")
        src, dest = pods[0], pods[1]
        who = src["seats"][1]["entrantId"]

        r = move(client, code, dest["podId"], who)
        assert r.status_code == 200, r.text
        assert r.json() == {
            "ok": True, "moved": True,
            "from": src["table"], "to": dest["table"], "seat": len(dest["seats"]) + 1,
        }

        after = {p["podId"]: p for p in pods_of(client, code)}
        assert who not in members(after[src["podId"]])
        assert who in members(after[dest["podId"]])
        # everyone is still seated exactly once, across the whole round
        seated = [s["entrantId"] for p in after.values() for s in p["seats"]]
        assert len(seated) == len(set(seated)) == 12

    def test_the_table_they_left_keeps_a_gapless_turn_order(self, client):
        code, pods = event(client, "moveB")
        src, dest = pods[0], pods[1]
        move(client, code, dest["podId"], src["seats"][0]["entrantId"])
        after = {p["podId"]: p for p in pods_of(client, code)}
        assert [s["seat"] for s in after[src["podId"]]["seats"]] == [1, 2, 3]
        assert [s["seat"] for s in after[dest["podId"]]["seats"]] == [1, 2, 3, 4, 5]

    def test_moving_is_idempotent(self, client):
        """Two organizers tapping the same thing is not an error."""
        code, pods = event(client, "moveC")
        who = pods[0]["seats"][0]["entrantId"]
        assert move(client, code, pods[0]["podId"], who).json() == {
            "ok": True, "moved": False, "from": pods[0]["table"], "to": pods[0]["table"]
        }
        assert len(pods_of(client, code)[0]["seats"]) == 4

    def test_only_the_organizer_may_move_anyone(self, client):
        code, pods = event(client, "moveD")
        who = pods[0]["seats"][0]["entrantId"]
        client.cookies.clear()
        assert move(client, code, pods[1]["podId"], who).status_code == 401
        organizer(client, "moveD-stranger")
        assert move(client, code, pods[1]["podId"], who).status_code == 403

    def test_an_unknown_entrant_is_a_404(self, client):
        code, pods = event(client, "moveE")
        assert move(client, code, pods[0]["podId"], "not-an-entrant").status_code == 404

    def test_a_dropped_entrant_is_not_seated(self, client):
        code, pods = event(client, "moveF")
        who = pods[0]["seats"][0]["entrantId"]
        client.post(f"/api/tournament/{code}/entrants/{who}/drop")
        r = move(client, code, pods[1]["podId"], who)
        assert r.status_code == 409 and "dropped" in r.json()["detail"]

    def test_a_late_entrant_can_be_seated_without_re_pairing(self, client):
        """Somebody who registers after the round was paired has no seat at all;
        the same endpoint puts them at a table."""
        code, pods = event(client, "moveG")
        late = add(client, code, ["latecomer"])[0]["entrantId"]
        r = move(client, code, pods[0]["podId"], late)
        assert r.status_code == 200 and r.json()["from"] is None
        seated = pods_of(client, code)[0]
        assert late in members(seated)
        assert len(seated["seats"]) == 5


class TestSeatsAndTokensFollowTheMove:
    def test_the_old_room_token_dies_and_a_new_one_arrives(self, client):
        code, pods = event(client, "tokA")
        src, dest = pods[0], pods[1]
        who = src["seats"][2]["entrantId"]
        entrant_token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": who}
        ).json()["entrantToken"]

        before = client.get(f"/api/tournament/{code}?token={entrant_token}").json()["myPod"]
        old_room, old_token = before["roomCode"], before["roomToken"]
        assert client.get(
            f"/api/table/rooms/{old_room}/me", headers={"X-Player-Token": old_token}
        ).status_code == 200

        move(client, code, dest["podId"], who)

        # the player's own poll is how their phone learns where they now sit
        now = client.get(f"/api/tournament/{code}?token={entrant_token}").json()["myPod"]
        assert now["podId"] == dest["podId"]
        assert now["roomCode"] != old_room
        assert now["roomToken"] and now["roomToken"] != old_token
        assert client.get(
            f"/api/table/rooms/{now['roomCode']}/me", headers={"X-Player-Token": now["roomToken"]}
        ).status_code == 200
        # and the token their phone was holding no longer opens the old table
        assert client.get(
            f"/api/table/rooms/{old_room}/me", headers={"X-Player-Token": old_token}
        ).status_code in (403, 404)

    def test_they_are_gone_from_the_room_they_left(self, client):
        code, pods = event(client, "tokB")
        src, dest = pods[0], pods[1]
        seat = src["seats"][1]
        move(client, code, dest["podId"], seat["entrantId"])
        left = client.get(f"/api/table/rooms/{src['roomCode']}/seats").json()["seats"]
        assert seat["name"] not in [s["name"] for s in left if not s["vacant"]]
        joined = client.get(f"/api/table/rooms/{dest['roomCode']}/seats").json()["seats"]
        assert seat["name"] in [s["name"] for s in joined]

    def test_moving_the_host_hands_the_room_on(self, client):
        """Seat 1 hosts the pod's room. A table with no host cannot start."""
        code, pods = event(client, "tokC")
        src, dest = pods[0], pods[1]
        move(client, code, dest["podId"], src["seats"][0]["entrantId"])
        hosts = q(
            "SELECT COUNT(*) AS c FROM players WHERE room_code = ? AND is_host = 1 AND left_game = 0",
            (src["roomCode"],),
        ).fetchone()["c"]
        assert hosts == 1

    def test_a_mid_game_arrival_starts_on_the_room_resource(self, client):
        code, pods = event(client, "tokD")
        src, dest = pods[0], pods[1]
        host_token = q(
            "SELECT room_token FROM pod_seats WHERE pod_id = ? ORDER BY seat LIMIT 1",
            (dest["podId"],),
        ).fetchone()["room_token"]
        client.post(
            f"/api/table/rooms/{dest['roomCode']}/start", headers={"X-Player-Token": host_token}
        )
        who = src["seats"][1]
        move(client, code, dest["podId"], who["entrantId"])
        state = client.get(
            f"/api/table/rooms/{dest['roomCode']}/me", headers={"X-Player-Token": host_token}
        ).json()
        arrived = next(p for p in state["players"] if p["name"] == who["name"])
        assert arrived["life"] == state["room"]["startingLife"]


class TestLimitsAndResults:
    def test_a_pod_cannot_grow_past_the_pairer_ceiling(self, client):
        code, pods = event(client, "capA")   # 12 entrants, pods of 4, podSize 4
        first = move(client, code, pods[1]["podId"], pods[0]["seats"][0]["entrantId"])
        assert first.status_code == 200      # table 2 now seats 5, the pairer's own maximum
        r = move(client, code, pods[1]["podId"], pods[2]["seats"][0]["entrantId"])
        assert r.status_code == 409 and "seats 5" in r.json()["detail"]

    def test_a_pod_cannot_shrink_below_three(self, client):
        code, pods = event(client, "capB")
        assert move(client, code, pods[1]["podId"], pods[0]["seats"][0]["entrantId"]).status_code == 200
        r = move(client, code, pods[2]["podId"], pods[0]["seats"][1]["entrantId"])
        assert r.status_code == 409 and "never goes below 3" in r.json()["detail"]

    def test_a_reported_table_is_frozen_both_ways(self, client):
        """A result is a ruling about a set of players. Moving anyone in or out
        of it afterwards would rewrite a decided game."""
        code, pods = event(client, "capC")
        decided, other = pods[0], pods[1]
        client.post(
            f"/api/tournament/{code}/pods/{decided['podId']}/result",
            json={"kind": "draw", "note": "time called"},
        )
        out = move(client, code, other["podId"], decided["seats"][0]["entrantId"])
        assert out.status_code == 409 and "already has a result" in out.json()["detail"]
        into = move(client, code, decided["podId"], other["seats"][0]["entrantId"])
        assert into.status_code == 409 and "already has a result" in into.json()["detail"]
        # and the ruling is untouched
        seats = q(
            "SELECT points FROM pod_seats WHERE pod_id = ?", (decided["podId"],)
        ).fetchall()
        assert [s["points"] for s in seats] == [1, 1, 1, 1]

    def test_nothing_moves_once_the_round_is_closed(self, client):
        code, pods = event(client, "capD")
        for pod in pods:
            client.post(
                f"/api/tournament/{code}/pods/{pod['podId']}/result", json={"kind": "draw"}
            )
        assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
        r = move(client, code, pods[1]["podId"], pods[0]["seats"][0]["entrantId"])
        assert r.status_code == 409 and "no round is open" in r.json()["detail"]

    def test_history_and_standings_follow_the_seats(self, client):
        """`met_history` and standings are derived from `pod_seats`, so the pod
        somebody actually played is the one recorded — nothing to repair."""
        code, pods = event(client, "capE")
        src, dest = pods[0], pods[1]
        seat = src["seats"][0]
        internal = q(
            "SELECT id FROM entrants WHERE tournament_code = ? AND public_id = ?",
            (code, seat["entrantId"]),
        ).fetchone()["id"]
        move(client, code, dest["podId"], seat["entrantId"])

        met = met_history(code)
        after = {p["podId"]: p for p in pods_of(client, code)}
        expected = {
            q("SELECT id FROM entrants WHERE tournament_code = ? AND public_id = ?",
              (code, s["entrantId"])).fetchone()["id"]
            for s in after[dest["podId"]]["seats"] if s["entrantId"] != seat["entrantId"]
        }
        assert set(met[internal]) == expected, "they met the table they played, not the one they left"

        # nothing has been decided, so nobody has points and the move cost none
        standings = client.get(f"/api/tournament/{code}").json()["standings"]
        assert {s["points"] for s in standings} == {0}
        assert len(standings) == 12


class TestSeatOrder:
    def test_the_organizer_can_set_turn_order(self, client):
        code, pods = event(client, "seatA", settings={"seatAssignment": "manual"})
        pod = pods[0]
        wanted = [s["entrantId"] for s in reversed(pod["seats"])]
        r = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/seats", json={"entrantIds": wanted}
        )
        assert r.status_code == 200, r.text
        after = next(p for p in pods_of(client, code) if p["podId"] == pod["podId"])
        assert [s["entrantId"] for s in after["seats"]] == wanted
        # the room behind the pod seats the same people in the same order
        room_names = [
            s["name"] for s in client.get(f"/api/table/rooms/{pod['roomCode']}/seats").json()["seats"]
        ]
        assert room_names == [s["name"] for s in after["seats"]]

    def test_a_partial_order_is_rejected(self, client):
        code, pods = event(client, "seatB")
        pod = pods[0]
        half = [s["entrantId"] for s in pod["seats"][:2]]
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/seats", json={"entrantIds": half})
        assert r.status_code == 400
        r = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/seats",
            json={"entrantIds": [s["entrantId"] for s in pod["seats"]] + [half[0]]},
        )
        assert r.status_code == 400
        unchanged = next(p for p in pods_of(client, code) if p["podId"] == pod["podId"])
        assert [s["seat"] for s in unchanged["seats"]] == [1, 2, 3, 4]

    def test_seat_assignment_is_validated_on_create(self, client):
        """A value seat_pods() does not implement would silently fall through to
        random — a different fairness decision from the one that was asked for."""
        organizer(client, "seatC")
        r = client.post(
            "/api/tournament", json={"name": "x", "settings": {"seatAssignment": "sideways"}}
        )
        assert r.status_code == 400 and "seatAssignment" in r.json()["detail"]
        ok = client.post(
            "/api/tournament", json={"name": "x", "settings": {"seatAssignment": "manual"}}
        )
        assert ok.status_code == 200


class TestNamingATable:
    def test_a_named_table_shows_up_everywhere_it_is_called(self, client):
        code, pods = event(client, "nameA")
        pod = pods[0]
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/name", json={"name": "Feature"})
        assert r.status_code == 200 and r.json()["name"] == "Feature"
        assert next(p for p in pods_of(client, code) if p["podId"] == pod["podId"])["name"] == "Feature"
        # the players' own view of the table is the room, so the name has to reach it
        token = q(
            "SELECT room_token FROM pod_seats WHERE pod_id = ? ORDER BY seat LIMIT 1",
            (pod["podId"],),
        ).fetchone()["room_token"]
        room = client.get(
            f"/api/table/rooms/{pod['roomCode']}/me", headers={"X-Player-Token": token}
        ).json()
        assert room["tournament"]["tableName"] == "Feature"
        assert room["tournament"]["table"] == pod["table"]

    def test_clearing_a_name_returns_the_table_to_its_number(self, client):
        code, pods = event(client, "nameB")
        pod = pods[0]
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/name", json={"name": "Feature"})
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/name", json={"name": "  "})
        assert r.status_code == 200 and r.json()["name"] is None
        assert next(p for p in pods_of(client, code) if p["podId"] == pod["podId"])["name"] is None

    def test_two_tables_in_a_round_cannot_share_a_name(self, client):
        code, pods = event(client, "nameC")
        client.post(f"/api/tournament/{code}/pods/{pods[0]['podId']}/name", json={"name": "Feature"})
        r = client.post(
            f"/api/tournament/{code}/pods/{pods[1]['podId']}/name", json={"name": "feature"}
        )
        assert r.status_code == 409
        assert next(p for p in pods_of(client, code) if p["podId"] == pods[1]["podId"])["name"] is None

    def test_naming_is_organizer_only(self, client):
        code, pods = event(client, "nameD")
        organizer(client, "nameD-stranger")
        r = client.post(f"/api/tournament/{code}/pods/{pods[0]['podId']}/name", json={"name": "Mine"})
        assert r.status_code == 403
