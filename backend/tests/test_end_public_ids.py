"""POST /{code}/end serves standings on the wire, so it obeys the same rule as
every other boundary: the integer primary key never leaves the server.

It used to return standings_rows() verbatim, which carries the internal id
under "entrantId" plus a separate "publicId". Clients type that field as an
opaque string, so the leak was silent. These tests pin the translated shape.
"""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.tournaments import router as tournaments_router
from conftest import verified_email


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def organizer(client, username):
    client.cookies.clear()
    client.post(
        "/api/account/signup",
        json={"username": username, "password": "a good long password"},
    )
    # hosting requires a recovery email
    verified_email(username)
    return client


def host(client, name="Ending Soon"):
    r = client.post("/api/tournament", json={"name": name, "settings": {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def played_event(client, username, names=("e1", "e2", "e3", "e4")):
    """An event with one full round played and closed — the state /end runs in."""
    organizer(client, username)
    code = host(client)
    client.post(f"/api/tournament/{code}/entrants", json={"names": list(names)})
    assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
    state = client.get(f"/api/tournament/{code}").json()
    for pod in state["pods"]:
        places = [
            {"entrantId": s["entrantId"], "place": i}
            for i, s in enumerate(pod["seats"], 1)
        ]
        r = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places},
        )
        assert r.status_code == 200, r.text
    assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
    return code


class TestEndReturnsPublicIds:
    def test_no_internal_id_appears_in_the_end_response(self, client):
        code = played_event(client, "enderA")
        internal = {
            r["id"]
            for r in q(
                "SELECT id FROM entrants WHERE tournament_code = ?", (code,)
            ).fetchall()
        }
        body = client.post(f"/api/tournament/{code}/end").json()
        wire = [s["entrantId"] for s in body["standings"]]
        assert wire, "the event had entrants; standings must not be empty"
        # not the integer, and not the integer stringified
        assert all(not isinstance(i, int) for i in wire)
        assert not (set(wire) & {str(i) for i in internal})
        # nor smuggled under a second key
        assert "publicId" not in json.dumps(body)

    def test_the_ids_it_returns_resolve_as_public_ids(self, client):
        code = played_event(client, "enderB")
        body = client.post(f"/api/tournament/{code}/end").json()
        for row in body["standings"]:
            found = q(
                "SELECT name FROM entrants WHERE tournament_code = ? AND public_id = ?",
                (code, row["entrantId"]),
            ).fetchone()
            assert found is not None, f"{row['entrantId']} is not a public id"
            assert found["name"] == row["name"]

    def test_end_standings_match_the_snapshot_exactly(self, client):
        """One shape, one sort. A frozen final table that disagreed with the
        snapshot the players are still polling would be worse than either."""
        code = played_event(client, "enderC")
        before = client.get(f"/api/tournament/{code}").json()["standings"]
        ended = client.post(f"/api/tournament/{code}/end").json()["standings"]
        assert ended == before
        after = client.get(f"/api/tournament/{code}").json()["standings"]
        assert ended == after

    def test_the_scoring_fields_survive_the_translation(self, client):
        """Only the id changes at the boundary — points and tiebreakers stay."""
        code = played_event(client, "enderD")
        rows = client.post(f"/api/tournament/{code}/end").json()["standings"]
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
        for row in rows:
            assert {"points", "opponentPoints", "podsPlayed", "wins", "draws",
                    "losses", "claimed", "dropped"} <= set(row)
            assert row["podsPlayed"] == 1
        assert sum(r["wins"] for r in rows) == 1
