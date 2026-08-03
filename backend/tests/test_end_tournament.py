"""Ending an event, including the events that cannot end tidily.

The ordinary path — close the last round, then end — was already covered. What
was not reachable at all was ending anything else: a tournament created by
mistake before a single round existed, and a tournament that dissolved mid-round
and can therefore never satisfy `close_round`'s "every pod has a result". Both
now have a way out, and the second one is deliberately destructive of nothing
except the unreported pods' scores.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.table import router as table_router
from app.tournaments import router as tournaments_router
from conftest import verified_email


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
    verified_email(username)
    return client


def host(client, name="Closing Night", settings=None):
    r = client.post("/api/tournament", json={"name": name, "settings": settings or {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def status_of(code):
    return q("SELECT status FROM tournaments WHERE code = ?", (code,)).fetchone()["status"]


class TestEndingBeforeAnyRound:
    """The case with no escape at all: an event created and then abandoned."""

    def test_a_tournament_with_no_rounds_can_be_ended(self, client):
        organizer(client, "endA")
        code = host(client)
        r = client.post(f"/api/tournament/{code}/end")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert status_of(code) == "ended"

    def test_a_tournament_with_a_roster_but_no_rounds_can_be_ended(self, client):
        organizer(client, "endB")
        code = host(client)
        add(client, code, ["a1", "a2", "a3", "a4"])
        assert client.post(f"/api/tournament/{code}/end").status_code == 200
        assert status_of(code) == "ended"

    def test_standings_come_back_empty_rather_than_erroring(self, client):
        organizer(client, "endC")
        code = host(client)
        add(client, code, ["b1", "b2"])
        body = client.post(f"/api/tournament/{code}/end").json()
        assert [row["points"] for row in body["standings"]] == [0, 0]


class TestForceEnd:
    """An event that empties out mid-round. `close_round` will never pass,
    because the pods that walked out are never going to report."""

    def test_an_open_round_still_blocks_an_ordinary_end(self, client):
        organizer(client, "endD")
        code = host(client)
        add(client, code, ["c1", "c2", "c3", "c4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        assert client.post(f"/api/tournament/{code}/end").status_code == 409
        assert status_of(code) == "running"

    def test_force_false_is_the_same_refusal(self, client):
        organizer(client, "endE")
        code = host(client)
        add(client, code, ["d1", "d2", "d3", "d4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/end", json={"force": False})
        assert r.status_code == 409

    def test_force_ends_it_and_closes_the_open_round(self, client):
        organizer(client, "endF")
        code = host(client)
        add(client, code, ["e1", "e2", "e3", "e4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/end", json={"force": True})
        assert r.status_code == 200, r.text
        assert status_of(code) == "ended"
        left_open = q(
            "SELECT COUNT(*) c FROM trounds WHERE tournament_code = ? AND status = 'active'",
            (code,),
        ).fetchone()["c"]
        assert left_open == 0

    def test_an_unreported_pod_scores_nothing_rather_than_guessing(self, client):
        organizer(client, "endG")
        code = host(client)
        add(client, code, ["f1", "f2", "f3", "f4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        body = client.post(f"/api/tournament/{code}/end", json={"force": True}).json()
        # nobody reported, so nobody scored — the event is over, not decided
        assert all(row["points"] == 0 for row in body["standings"])

    def test_results_reported_before_the_force_survive_it(self, client):
        organizer(client, "endH")
        code = host(client)
        ids = [e["entrantId"] for e in add(client, code, ["g1", "g2", "g3", "g4"])]
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        seats = [s["entrantId"] for s in pod["seats"]]
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={
                "kind": "placement",
                "places": [{"entrantId": e, "place": i} for i, e in enumerate(seats, 1)],
            },
        )
        body = client.post(f"/api/tournament/{code}/end", json={"force": True}).json()
        winner = next(r for r in body["standings"] if r["entrantId"] == seats[0])
        assert winner["points"] > 0
        assert set(ids) == {r["entrantId"] for r in body["standings"]}

    def test_force_is_still_an_organizer_only_power(self, client):
        organizer(client, "endI")
        code = host(client)
        add(client, code, ["h1", "h2", "h3", "h4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        organizer(client, "endJ")  # a different account entirely
        assert (
            client.post(f"/api/tournament/{code}/end", json={"force": True}).status_code == 403
        )
        assert status_of(code) == "running"

    def test_ending_twice_is_not_an_error_worth_showing(self, client):
        organizer(client, "endK")
        code = host(client)
        client.post(f"/api/tournament/{code}/end")
        second = client.post(f"/api/tournament/{code}/end")
        assert second.status_code in (200, 409)
        assert status_of(code) == "ended"
