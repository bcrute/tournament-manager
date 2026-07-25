"""The game profile's resource family is load-bearing.

`resource`, `resource_start`, `resource_direction` and `resource_goal` used to
be four fields two of which nothing read: time-called ranking hardcoded a
descending sort on the room's life column, so a game whose resource counted
*up* would have been ranked backwards, and `/games` never told a client which
way the resource moved anyway.
"""

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import games
from app.accounts import router as accounts_router
from app.db import q
from app.games import MTG, canonical_policy
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
    client.post("/api/account/signup",
                json={"username": username, "password": "a good long password"})
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, game="mtg", mode="life", settings=None):
    r = client.post("/api/tournament", json={
        "name": "Resource Night", "game": game, "mode": mode, "settings": settings or {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def seats_of(client, code):
    pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
    rows = q("SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
             "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
             (pod["podId"],)).fetchall()
    return pod, rows


def run_time_called(client, code, pod_id, resources, seats):
    """Set each seat's tracked resource, call time, tap through the turns."""
    for s, value in zip(seats, resources):
        q("UPDATE players SET life = ? WHERE token = ?", (value, s["room_token"]))
    client.post(f"/api/tournament/{code}/rounds/time")
    for _ in range(MTG.extra_turns_at_time):
        client.post(f"/api/tournament/{code}/pods/{pod_id}/turn", json={"delta": -1})
    after = client.get(f"/api/tournament/{code}").json()["pods"][0]
    return {s["entrantId"]: s["place"] for s in after["seats"]}


class TestResourceIsAdvertised:
    def test_games_emits_the_whole_resource_family(self, client):
        mtg = client.get("/api/tournament/games").json()["games"][0]
        assert mtg["resource"] == MTG.resource
        assert mtg["resourceStart"] == MTG.resource_start == 40
        assert mtg["resourceDirection"] == MTG.resource_direction == "down"
        assert mtg["resourceGoal"] == MTG.resource_goal == 0

    def test_the_offered_policy_is_named_for_the_resource_not_for_life(self, client):
        mtg = client.get("/api/tournament/games").json()["games"][0]
        assert "highest_resource" in mtg["timeCalledPolicies"]
        assert "highest_life" not in mtg["timeCalledPolicies"]


class TestPolicyAlias:
    """`highest_life` is persisted in live tournaments' settings JSON. Dropping
    it would break events that are running right now."""

    def test_the_old_spelling_is_still_accepted_and_stored_canonically(self, client):
        organizer(client, "resA")
        code = host(client, settings={"timeCalledPolicy": "highest_life"})
        cfg = client.get(f"/api/tournament/{code}").json()["tournament"]["settings"]
        assert cfg["timeCalledPolicy"] == "highest_resource"

    def test_the_new_spelling_is_accepted(self, client):
        organizer(client, "resB")
        code = host(client, settings={"timeCalledPolicy": "highest_resource"})
        cfg = client.get(f"/api/tournament/{code}").json()["tournament"]["settings"]
        assert cfg["timeCalledPolicy"] == "highest_resource"

    def test_a_settings_row_written_before_the_rename_still_resolves(self, client):
        """The stored JSON is what matters: canonicalising on write does nothing
        for the tournaments that were created last week."""
        organizer(client, "resC")
        code = host(client, settings={"timeCalledPolicy": "highest_resource"})
        q("UPDATE tournaments SET settings = ? WHERE code = ?",
          ('{"timeCalledPolicy": "highest_life"}', code))
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["r1", "r2", "r3", "r4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, seats = seats_of(client, code)
        place = run_time_called(client, code, pod["podId"], [4, 21, 9, 13], seats)
        by_public = {s["public_id"]: v for s, v in zip(seats, [4, 21, 9, 13])}
        ordered = sorted(by_public, key=lambda p: place[p])
        assert [by_public[p] for p in ordered] == [21, 13, 9, 4]

    def test_canonical_policy_leaves_everything_else_alone(self):
        assert canonical_policy("highest_life") == "highest_resource"
        assert canonical_policy("highest_resource") == "highest_resource"
        assert canonical_policy("draw_all") == "draw_all"
        assert canonical_policy(None) is None


class TestRankingFollowsTheProfile:
    def test_a_down_counting_resource_ranks_the_highest_total_first(self, client):
        organizer(client, "resD")
        code = host(client, settings={"timeCalledPolicy": "highest_resource"})
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["d1", "d2", "d3", "d4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, seats = seats_of(client, code)
        lives = [8, 33, 17, 2]
        place = run_time_called(client, code, pod["podId"], lives, seats)
        by_public = {s["public_id"]: v for s, v in zip(seats, lives)}
        ordered = sorted(by_public, key=lambda p: place[p])
        assert [by_public[p] for p in ordered] == [33, 17, 8, 2]

    def test_an_up_counting_resource_ranks_the_lowest_total_first(self, client, monkeypatch):
        """A resource that counts *up* to the value that ends the game (poison,
        corruption) puts the player furthest from that value on top. Under the
        old hardcoded descending sort this pod came out exactly backwards."""
        pressure = dataclasses.replace(
            MTG, key="pressure", name="Pressure", resource="doom",
            resource_start=0, resource_direction="up", resource_goal=10,
        )
        monkeypatch.setitem(games._PROFILES, "pressure", pressure)
        organizer(client, "resE")
        code = host(client, game="pressure", settings={"timeCalledPolicy": "highest_resource"})
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["u1", "u2", "u3", "u4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, seats = seats_of(client, code)
        doom = [8, 1, 6, 3]
        place = run_time_called(client, code, pod["podId"], doom, seats)
        by_public = {s["public_id"]: v for s, v in zip(seats, doom)}
        ordered = sorted(by_public, key=lambda p: place[p])
        assert [by_public[p] for p in ordered] == [1, 3, 6, 8]

    def test_a_tie_on_an_up_counting_resource_is_still_a_genuine_tie(self, client, monkeypatch):
        pressure = dataclasses.replace(
            MTG, key="pressure2", name="Pressure", resource="doom",
            resource_start=0, resource_direction="up", resource_goal=10,
        )
        monkeypatch.setitem(games._PROFILES, "pressure2", pressure)
        organizer(client, "resF")
        code = host(client, game="pressure2", settings={"timeCalledPolicy": "highest_resource"})
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["v1", "v2", "v3", "v4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, seats = seats_of(client, code)
        doom = [2, 2, 5, 9]
        place = run_time_called(client, code, pod["podId"], doom, seats)
        by_public = {s["public_id"]: v for s, v in zip(seats, doom)}
        tied = [p for p, v in by_public.items() if v == 2]
        assert place[tied[0]] == place[tied[1]] == 1
        assert place[[p for p, v in by_public.items() if v == 5][0]] == 3
        assert place[[p for p, v in by_public.items() if v == 9][0]] == 4

    def test_rank_key_orders_both_directions(self):
        assert sorted([12, 30, 5], key=MTG.resource_rank_key) == [30, 12, 5]
        up = dataclasses.replace(MTG, resource_direction="up", resource_start=0,
                                 resource_goal=10)
        assert sorted([12, 30, 5], key=up.resource_rank_key) == [5, 12, 30]


class TestResultNote:
    def test_the_note_takes_its_wording_from_the_profile(self, client, monkeypatch):
        pressure = dataclasses.replace(
            MTG, key="pressure3", name="Pressure", resource="doom",
            resource_start=0, resource_direction="up", resource_goal=10,
        )
        monkeypatch.setitem(games._PROFILES, "pressure3", pressure)
        organizer(client, "resG")
        code = host(client, game="pressure3", settings={"timeCalledPolicy": "highest_resource"})
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["w1", "w2", "w3", "w4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, seats = seats_of(client, code)
        run_time_called(client, code, pod["podId"], [1, 2, 3, 4], seats)
        note = q("SELECT note FROM pod_results WHERE pod_id = ? ORDER BY version DESC",
                 (pod["podId"],)).fetchone()["note"]
        assert note == "time called — ranked on doom"

    def test_an_mtg_pod_still_says_life(self, client):
        organizer(client, "resH")
        code = host(client, settings={"timeCalledPolicy": "highest_resource"})
        client.post(f"/api/tournament/{code}/entrants",
                    json={"names": ["x1", "x2", "x3", "x4"]})
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, seats = seats_of(client, code)
        run_time_called(client, code, pod["podId"], [10, 20, 30, 40], seats)
        note = q("SELECT note FROM pod_results WHERE pod_id = ? ORDER BY version DESC",
                 (pod["podId"],)).fetchone()["note"]
        assert note == "time called — ranked on life"
