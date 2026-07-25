"""Historical rounds: `GET /{code}/rounds/{n}`.

The live snapshot carries only the latest round, so once round 2 opens nobody
could answer "who did I play in round 1, and what did we end up with?". These
pin that the answer is readable, and that reading it back leaks nothing the
round did not already expose while it was live.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
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
    r = client.post(
        "/api/tournament", json={"name": name, "mode": "life", "settings": settings or {}}
    )
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def two_rounds(client, username, names=("h1", "h2", "h3", "h4")):
    """A tournament whose round 1 is played, resolved and closed, with round 2
    open on top of it — the state where the live snapshot has stopped showing
    round 1 at all. Returns (code, round-1 pods, entrants)."""
    organizer(client, username)
    code = host(client)
    added = add(client, code, list(names))
    client.post(f"/api/tournament/{code}/rounds", json={})
    pods = client.get(f"/api/tournament/{code}").json()["pods"]
    for pod in pods:
        places = [
            {"entrantId": s["entrantId"], "place": i} for i, s in enumerate(pod["seats"], 1)
        ]
        r = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places, "note": "table 1 ruling"},
        )
        assert r.status_code == 200, r.text
    assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
    assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
    return code, pods, added


class TestRoundHistory:
    def test_a_past_round_is_still_readable_after_the_next_one_opens(self, client):
        code, pods, _ = two_rounds(client, "histA")
        live = client.get(f"/api/tournament/{code}").json()
        assert live["round"]["number"] == 2  # the snapshot has moved on

        past = client.get(f"/api/tournament/{code}/rounds/1").json()
        assert past["round"]["number"] == 1
        assert past["round"]["status"] == "closed"
        assert [p["podId"] for p in past["pods"]] == [p["podId"] for p in pods]
        assert [
            [s["entrantId"] for s in p["seats"]] for p in past["pods"]
        ] == [[s["entrantId"] for s in p["seats"]] for p in pods]

    def test_seats_and_results_are_as_they_were(self, client):
        code, pods, added = two_rounds(client, "histB")
        pod = client.get(f"/api/tournament/{code}/rounds/1").json()["pods"][0]
        assert [s["place"] for s in pod["seats"]] == [1, 2, 3, 4]
        assert [s["points"] for s in pod["seats"]] == [3, 0, 0, 0]
        assert pod["result"]["kind"] == "placement"
        assert pod["result"]["source"] == "organizer"
        assert pod["result"]["version"] == 1

    def test_a_draw_is_distinguishable_from_four_firsts(self, client):
        """Every seat in a draw is place 1, so placings alone cannot say whether
        the pod was drawn or somehow won four ways. The result kind can."""
        organizer(client, "histC")
        code = host(client)
        added = add(client, code, ["d1", "d2", "d3", "d4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "draw", "places": [{"entrantId": e["entrantId"], "place": 1} for e in added]},
        )
        past = client.get(f"/api/tournament/{code}/rounds/1").json()
        assert past["pods"][0]["result"]["kind"] == "draw"
        assert all(s["place"] == 1 for s in past["pods"][0]["seats"])

    def test_an_override_reads_back_as_the_standing_decision(self, client):
        code, pods, added = two_rounds(client, "histD")
        pod_id = pods[0]["podId"]
        flipped = [
            {"entrantId": s["entrantId"], "place": i}
            for i, s in enumerate(reversed(pods[0]["seats"]), 1)
        ]
        client.post(
            f"/api/tournament/{code}/pods/{pod_id}/result",
            json={"kind": "placement", "places": flipped, "note": "misreported"},
        )
        pod = client.get(f"/api/tournament/{code}/rounds/1").json()["pods"][0]
        assert pod["result"]["version"] == 2 and pod["result"]["note"] == "misreported"
        assert [s["place"] for s in pod["seats"]] == [4, 3, 2, 1]

    def test_an_unknown_round_is_a_404(self, client):
        code, _, _ = two_rounds(client, "histE")
        assert client.get(f"/api/tournament/{code}/rounds/9").status_code == 404
        assert client.get("/api/tournament/ZZZZZ/rounds/1").status_code == 404

    def test_the_round_still_open_is_readable_too(self, client):
        code, _, _ = two_rounds(client, "histF")
        past = client.get(f"/api/tournament/{code}/rounds/2").json()
        assert past["round"]["number"] == 2 and past["round"]["status"] == "active"
        assert past["pods"] and past["pods"][0]["result"] is None


class TestRoundHistoryViewRules:
    """The historical view is the live view's rules applied to an older round.
    If it ever diverges, a past round becomes a way around them."""

    def test_the_room_code_stays_organizer_only(self, client):
        code, _, _ = two_rounds(client, "histG")
        assert all(p["roomCode"] for p in client.get(f"/api/tournament/{code}/rounds/1").json()["pods"])
        client.cookies.clear()
        anon = client.get(f"/api/tournament/{code}/rounds/1").json()
        assert anon["isOrganizer"] is False
        assert all(p["roomCode"] is None for p in anon["pods"])
        assert anon["myPod"] is None and anon["me"] is None

    def test_a_room_token_reaches_only_the_callers_own_seat(self, client):
        code, pods, added = two_rounds(client, "histH")
        client.cookies.clear()
        token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]}
        ).json()["entrantToken"]
        past = client.get(f"/api/tournament/{code}/rounds/1", params={"token": token}).json()
        assert past["me"]["entrantId"] == added[0]["entrantId"]
        assert past["myPod"]["roomToken"] and past["myPod"]["roomCode"]
        assert any(s["entrantId"] == added[0]["entrantId"] for s in past["myPod"]["seats"])
        for pod in past["pods"]:
            assert "roomToken" not in pod
            for seat in pod["seats"]:
                assert "roomToken" not in seat and "room_token" not in seat

    def test_the_integer_primary_key_never_goes_on_the_wire(self, client):
        code, _, added = two_rounds(client, "histI")
        past = client.get(f"/api/tournament/{code}/rounds/1").json()
        public = {e["entrantId"] for e in added}
        for pod in past["pods"]:
            for seat in pod["seats"]:
                assert seat["entrantId"] in public
                assert not str(seat["entrantId"]).isdigit()

    def test_an_organizer_ruling_note_is_not_shown_to_the_table(self, client):
        """A note is written for staff. Placings and the kind are the table's
        business; the reasoning behind an override is not."""
        code, _, added = two_rounds(client, "histJ")
        client.cookies.clear()
        token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]}
        ).json()["entrantToken"]
        past = client.get(f"/api/tournament/{code}/rounds/1", params={"token": token}).json()
        assert past["pods"][0]["result"]["kind"] == "placement"
        assert "note" not in past["pods"][0]["result"]

    def test_another_organizers_session_reads_it_as_a_stranger(self, client):
        code, _, _ = two_rounds(client, "histK")
        organizer(client, "histKIntruder")  # a real account, not this event's
        past = client.get(f"/api/tournament/{code}/rounds/1").json()
        assert past["isOrganizer"] is False
        assert all(p["roomCode"] is None for p in past["pods"])
