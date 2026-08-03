"""A game profile with no modes: pods exist, rooms do not.

`games.py` has always promised that "a game with no room support simply has
none and is scored by hand". These tests hold the server to it, using a
synthetic profile registered for the duration of the module — adding a real
game to the registry is a separate decision, and this behaviour must be
testable without one.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import games
from app.accounts import router as accounts_router
from app.db import q
from app.games import GameProfile
from app.table import router as table_router
from app.tournaments import router as tournaments_router
from conftest import verified_email


HANDSCORED = GameProfile(
    key="handscored",
    name="Hand-Scored Test Game",
    publisher="Nobody",
    default_pod_size=4,
    default_round_minutes=50,
    resource="points",
    resource_start=0,
    resource_direction="up",
    resource_goal=10,
    modes=(),                      # the whole point: no live table state
    time_called_policies=("draw_all",),
)


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    games._PROFILES[HANDSCORED.key] = HANDSCORED
    try:
        with TestClient(app, base_url="https://testserver") as c:
            yield c
    finally:
        games._PROFILES.pop(HANDSCORED.key, None)


def organizer(client, username):
    client.cookies.clear()
    client.post("/api/account/signup", json={"username": username, "password": "a good long password"})
    verified_email(username)
    return client


def host(client, name="Hand night", body=None):
    payload = {"name": name, "game": "handscored"}
    payload.update(body or {})
    r = client.post("/api/tournament", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def rooms_count():
    return q("SELECT COUNT(*) c FROM rooms").fetchone()["c"]


class TestModelessProfileCreation:
    def test_a_mode_is_rejected_outright(self, client):
        organizer(client, "roomlessA")
        r = client.post("/api/tournament",
                        json={"name": "x", "game": "handscored", "mode": "life"})
        assert r.status_code == 400 and "hand" in r.json()["detail"]

    def test_even_an_invented_mode_is_rejected_rather_than_stored(self, client):
        """The old code only validated `if profile.modes`, so any string went
        straight into the row for a modeless game."""
        organizer(client, "roomlessB")
        r = client.post("/api/tournament",
                        json={"name": "x", "game": "handscored", "mode": "whatever"})
        assert r.status_code == 400

    def test_omitting_the_mode_stores_the_documented_empty_value(self, client):
        organizer(client, "roomlessC")
        code = host(client)
        t = client.get(f"/api/tournament/{code}").json()["tournament"]
        assert t["game"] == "handscored" and t["mode"] == ""

    def test_a_game_with_modes_still_defaults_to_its_first_one(self, client):
        organizer(client, "roomlessD")
        r = client.post("/api/tournament", json={"name": "mtg night", "game": "mtg"})
        assert r.status_code == 200
        t = client.get(f"/api/tournament/{r.json()['code']}").json()["tournament"]
        assert t["mode"] == games.MTG.modes[0]


class TestRoomlessRounds:
    def test_opening_a_round_seats_pods_but_creates_no_rooms(self, client):
        organizer(client, "roomlessE")
        code = host(client)
        add(client, code, [f"p{i}" for i in range(8)])
        before = rooms_count()
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 200 and r.json()["pods"] == 2
        assert rooms_count() == before, "a hand-scored game must not spawn rooms"

        state = client.get(f"/api/tournament/{code}").json()
        assert len(state["pods"]) == 2
        for pod in state["pods"]:
            assert pod["roomCode"] is None
            assert [s["seat"] for s in pod["seats"]] == [1, 2, 3, 4]

        rows = q(
            "SELECT p.room_code FROM pods p JOIN trounds r ON r.id = p.round_id "
            "WHERE r.tournament_code = ?", (code,),
        ).fetchall()
        assert [row["room_code"] for row in rows] == [None, None]

    def test_a_player_snapshot_survives_a_pod_with_no_room(self, client):
        organizer(client, "roomlessF")
        code = host(client)
        entrants = add(client, code, [f"q{i}" for i in range(4)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        claim = client.post(f"/api/tournament/{code}/claim",
                            json={"entrantId": entrants[0]["entrantId"]})
        assert claim.status_code == 200, claim.text
        token = claim.json()["entrantToken"]

        client.cookies.clear()   # a plain entrant, not the organizer
        state = client.get(f"/api/tournament/{code}?token={token}").json()
        assert state["myPod"] is not None
        assert state["myPod"]["roomCode"] is None
        assert state["myPod"]["roomToken"] is None

    def test_the_organizer_reports_by_hand_and_the_round_closes(self, client):
        organizer(client, "roomlessG")
        code = host(client)
        entrants = add(client, code, [f"r{i}" for i in range(4)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        r = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement",
                  "places": [{"entrantId": s["entrantId"], "place": i}
                             for i, s in enumerate(pod["seats"], 1)]},
        )
        assert r.status_code == 200, r.text
        assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200

        standings = client.get(f"/api/tournament/{code}").json()["standings"]
        winner = next(s for s in standings if s["entrantId"] == pod["seats"][0]["entrantId"])
        assert winner["points"] > 0
        assert len(entrants) == 4

    def test_calling_time_decides_roomless_pods_instead_of_stranding_them(self, client):
        """With no room there are no life totals to rank and no turns to count,
        so time called is settled immediately as a draw."""
        organizer(client, "roomlessH")
        code = host(client)
        add(client, code, [f"s{i}" for i in range(4)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/rounds/time")
        assert r.status_code == 200, r.text
        assert r.json()["decided"] == 1 and r.json()["extraTurns"] == 0
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        assert all(p["status"] == "complete" for p in pods)
        assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
