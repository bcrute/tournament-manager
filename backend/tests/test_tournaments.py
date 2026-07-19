"""Tournament management: hosting, roster, rounds, results, standings, calls."""

import json
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


def organizer(client, username, with_email=True):
    client.cookies.clear()
    client.post("/api/account/signup", json={"username": username, "password": "a good long password"})
    if with_email:
        client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, name="Friday Night", mode="life", settings=None):
    r = client.post(
        "/api/tournament", json={"name": name, "mode": mode, "settings": settings or {}}
    )
    assert r.status_code == 200, r.text
    return r.json()["code"]


def seat_token(client, code, pod):
    """A token belonging to somebody actually sitting at this table. Calling an
    official is restricted to players at that table, so tests need one. Takes
    the first seat still unclaimed, so repeated calls return distinct players
    rather than failing on the second."""
    for seat in pod["seats"]:
        r = client.post(f"/api/tournament/{code}/claim", json={"entrantId": seat["entrantId"]})
        if r.status_code == 200:
            return r.json()["entrantToken"]
    raise AssertionError("every seat in this pod is already claimed")


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


class TestHosting:
    def test_requires_an_account(self, client):
        client.cookies.clear()
        assert client.post("/api/tournament", json={"name": "x"}).status_code == 401

    def test_requires_a_recovery_email(self, client):
        """An organizer locked out mid-event strands the whole room."""
        organizer(client, "noemail", with_email=False)
        r = client.post("/api/tournament", json={"name": "x"})
        assert r.status_code == 409
        assert "recovery email" in r.json()["detail"]

    def test_creates_with_a_code(self, client):
        organizer(client, "hostA")
        code = host(client)
        assert len(code) == 5
        state = client.get(f"/api/tournament/{code}").json()
        assert state["tournament"]["name"] == "Friday Night"
        assert state["isOrganizer"] is True

    def test_only_the_organizer_manages_it(self, client):
        organizer(client, "hostB")
        code = host(client)
        organizer(client, "otherB")  # different account
        assert client.post(f"/api/tournament/{code}/entrants", json={"names": ["x"]}).status_code == 403
        assert client.get(f"/api/tournament/{code}").json()["isOrganizer"] is False


class TestRosterAndClaims:
    def test_roster_is_public_so_players_can_claim(self, client):
        organizer(client, "hostC")
        code = host(client)
        add(client, code, ["ann", "bo", "cy", "di"])
        client.cookies.clear()  # a player, signed out
        roster = client.get(f"/api/tournament/{code}/roster").json()
        assert [e["name"] for e in roster["entrants"]] == ["ann", "bo", "cy", "di"]
        assert all(e["claimed"] is False for e in roster["entrants"])

    def test_claiming_by_id_not_name(self, client):
        organizer(client, "hostD")
        code = host(client)
        added = add(client, code, ["sam", "sam"])  # duplicate names are legal
        client.cookies.clear()
        first = client.post(f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]})
        assert first.status_code == 200
        second = client.post(f"/api/tournament/{code}/claim", json={"entrantId": added[1]["entrantId"]})
        assert second.status_code == 200
        assert first.json()["entrantToken"] != second.json()["entrantToken"]

    def test_a_claim_locks(self, client):
        organizer(client, "hostE")
        code = host(client)
        added = add(client, code, ["zoe"])
        client.cookies.clear()
        client.post(f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]})
        again = client.post(f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]})
        assert again.status_code == 409

    def test_organizer_can_release_a_wrong_claim(self, client):
        organizer(client, "hostF")
        code = host(client)
        added = add(client, code, ["kit"])
        eid = added[0]["entrantId"]
        client.post(f"/api/tournament/{code}/claim", json={"entrantId": eid})
        organizer(client, "hostF2")  # wrong account can't release
        assert client.post(f"/api/tournament/{code}/entrants/{eid}/release").status_code == 403


class TestRounds:
    def test_opening_a_round_pairs_and_creates_rooms(self, client):
        organizer(client, "hostG")
        code = host(client)
        add(client, code, [f"p{i}" for i in range(8)])
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 200 and r.json()["pods"] == 2
        state = client.get(f"/api/tournament/{code}").json()
        assert len(state["pods"]) == 2
        for pod in state["pods"]:
            assert pod["roomCode"], "every pod needs a room to play in"
            assert len(pod["seats"]) == 4
            assert [s["seat"] for s in pod["seats"]] == [1, 2, 3, 4]

    def test_pod_rooms_are_playable(self, client):
        """The room behind a pod is an ordinary room: the table app just works."""
        organizer(client, "hostH")
        code = host(client)
        add(client, code, [f"q{i}" for i in range(4)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        token = q(
            "SELECT room_token FROM pod_seats WHERE pod_id = ? ORDER BY seat LIMIT 1", (pod["podId"],)
        ).fetchone()["room_token"]
        me = client.get(
            f"/api/table/rooms/{pod['roomCode']}/me", headers={"X-Player-Token": token}
        )
        assert me.status_code == 200
        assert len(me.json()["players"]) == 4

    def test_everyone_is_seated_exactly_once(self, client):
        organizer(client, "hostI")
        code = host(client)
        add(client, code, [f"r{i}" for i in range(11)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        seated = [s["entrantId"] for p in pods for s in p["seats"]]
        assert len(seated) == len(set(seated)) == 11
        assert sorted(len(p["seats"]) for p in pods) == [3, 4, 4]

    def test_reroll_replaces_the_pairing(self, client):
        organizer(client, "hostJ")
        code = host(client)
        add(client, code, [f"s{i}" for i in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        before = [[s["entrantId"] for s in p["seats"]] for p in client.get(f"/api/tournament/{code}").json()["pods"]]
        client.post(f"/api/tournament/{code}/rounds", json={"reroll": True})
        state = client.get(f"/api/tournament/{code}").json()
        after = [[s["entrantId"] for s in p["seats"]] for p in state["pods"]]
        assert state["tournament"]["roundCount"] == 1, "a reroll is not a new round"
        assert before != after

    def test_a_second_round_needs_the_first_closed(self, client):
        organizer(client, "hostK")
        code = host(client)
        add(client, code, [f"t{i}" for i in range(4)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 409

    def test_dropped_players_are_not_paired(self, client):
        organizer(client, "hostL")
        code = host(client)
        added = add(client, code, [f"u{i}" for i in range(5)])
        client.post(f"/api/tournament/{code}/entrants/{added[0]['entrantId']}/drop")
        client.post(f"/api/tournament/{code}/rounds", json={})
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        seated = [s["entrantId"] for p in pods for s in p["seats"]]
        assert added[0]["entrantId"] not in seated
        assert len(seated) == 4


class TestResults:
    def _four_player_round(self, client, who):
        organizer(client, who)
        code = host(client)
        added = add(client, code, ["w", "x", "y", "z"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        return code, pod, added

    def test_organizer_records_a_placement(self, client):
        code, pod, added = self._four_player_round(client, "hostM")
        places = [{"entrantId": e["entrantId"], "place": i} for i, e in enumerate(added, 1)]
        r = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places},
        )
        assert r.status_code == 200
        standings = client.get(f"/api/tournament/{code}").json()["standings"]
        winner = next(s for s in standings if s["entrantId"] == added[0]["entrantId"])
        assert winner["points"] == 3 and winner["rank"] == 1

    def test_placement_scoring_option(self, client):
        organizer(client, "hostN")
        code = host(client, settings={"scoring": "placement", "placementPoints": [4, 3, 2, 1]})
        added = add(client, code, ["a1", "b1", "c1", "d1"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        places = [{"entrantId": e["entrantId"], "place": i} for i, e in enumerate(added, 1)]
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places},
        )
        standings = {s["entrantId"]: s["points"] for s in client.get(f"/api/tournament/{code}").json()["standings"]}
        assert [standings[e["entrantId"]] for e in added] == [4, 3, 2, 1]

    def test_draw_gives_everyone_draw_points(self, client):
        code, pod, added = self._four_player_round(client, "hostO")
        places = [{"entrantId": e["entrantId"], "place": 1} for e in added]
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "draw", "places": places},
        )
        standings = client.get(f"/api/tournament/{code}").json()["standings"]
        assert all(s["points"] == 1 for s in standings)

    def test_override_is_versioned_not_destructive(self, client):
        code, pod, added = self._four_player_round(client, "hostP")
        places = [{"entrantId": e["entrantId"], "place": i} for i, e in enumerate(added, 1)]
        first = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places},
        ).json()
        flipped = list(reversed(places))
        for i, p in enumerate(flipped, 1):
            p["place"] = i
        second = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": flipped, "note": "misreported"},
        ).json()
        assert second["version"] == first["version"] + 1
        rows = q("SELECT * FROM pod_results WHERE pod_id = ? ORDER BY version", (pod["podId"],)).fetchall()
        assert len(rows) == 2 and rows[0]["note"] is None and rows[1]["note"] == "misreported"

    def test_stale_override_is_rejected(self, client):
        code, pod, added = self._four_player_round(client, "hostQ")
        places = [{"entrantId": e["entrantId"], "place": i} for i, e in enumerate(added, 1)]
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places},
        )
        stale = client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement", "places": places, "expectedVersion": 0},
        )
        assert stale.status_code == 409

    def test_auto_result_from_the_room(self, client):
        """Play the pod out in the room; the tournament records it itself."""
        organizer(client, "hostR")
        code = host(client)
        added = add(client, code, ["m1", "m2", "m3", "m4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        seats = q(
            "SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
            "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
            (pod["podId"],),
        ).fetchall()
        room = pod["roomCode"]
        host_token = seats[0]["room_token"]
        client.post(f"/api/table/rooms/{room}/start", headers={"X-Player-Token": host_token})
        # three players die, last one standing wins
        for s in seats[1:]:
            client.post(
                f"/api/table/rooms/{room}/eliminate",
                headers={"X-Player-Token": s["room_token"]},
                json={},
            )
        standings = client.get(f"/api/tournament/{code}").json()["standings"]
        top = standings[0]
        assert top["entrantId"] == seats[0]["public_id"]
        assert top["points"] == 3
        result = q(
            "SELECT * FROM pod_results WHERE pod_id = ? ORDER BY version DESC LIMIT 1", (pod["podId"],)
        ).fetchone()
        assert result["source"] == "auto"

    def test_auto_never_overwrites_an_organizer_ruling(self, client):
        organizer(client, "hostS")
        code = host(client)
        added = add(client, code, ["n1", "n2", "n3", "n4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        seats = q(
            "SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
            "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
            (pod["podId"],),
        ).fetchall()
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "draw",
                  "places": [{"entrantId": s["public_id"], "place": 1} for s in seats],
                  "note": "time called"},
        )
        room = pod["roomCode"]
        client.post(f"/api/table/rooms/{room}/start", headers={"X-Player-Token": seats[0]["room_token"]})
        for s in seats[1:]:
            client.post(f"/api/table/rooms/{room}/eliminate",
                        headers={"X-Player-Token": s["room_token"]}, json={})
        latest = q(
            "SELECT * FROM pod_results WHERE pod_id = ? ORDER BY version DESC LIMIT 1", (pod["podId"],)
        ).fetchone()
        assert latest["source"] == "organizer", "an auto result overwrote a ruling"


class TestRoundClosing:
    def test_cannot_close_with_missing_results(self, client):
        organizer(client, "hostT")
        code = host(client)
        add(client, code, ["v1", "v2", "v3", "v4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/rounds/close")
        assert r.status_code == 409 and "no result" in r.json()["detail"]

    def test_cannot_close_over_an_open_official_call(self, client):
        organizer(client, "hostU")
        code = host(client)
        added = add(client, code, ["c1", "c2", "c3", "c4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement",
                  "places": [{"entrantId": e["entrantId"], "place": i} for i, e in enumerate(added, 1)]},
        )
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                    params={"token": seat_token(client, code, pod)}, json={"category": "rules"})
        blocked = client.post(f"/api/tournament/{code}/rounds/close")
        assert blocked.status_code == 409 and "official call" in blocked.json()["detail"]

    def test_closing_then_a_second_round(self, client):
        organizer(client, "hostV")
        code = host(client)
        added = add(client, code, [f"w{i}" for i in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        for pod in client.get(f"/api/tournament/{code}").json()["pods"]:
            client.post(
                f"/api/tournament/{code}/pods/{pod['podId']}/result",
                json={"kind": "placement",
                      "places": [{"entrantId": s["entrantId"], "place": i}
                                 for i, s in enumerate(pod["seats"], 1)]},
            )
        assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
        assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
        assert client.get(f"/api/tournament/{code}").json()["tournament"]["roundCount"] == 2

    def test_second_round_avoids_rematches(self, client):
        organizer(client, "hostW")
        code = host(client)
        add(client, code, [f"x{i}" for i in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        first = [frozenset(s["entrantId"] for s in p["seats"])
                 for p in client.get(f"/api/tournament/{code}").json()["pods"]]
        for pod in client.get(f"/api/tournament/{code}").json()["pods"]:
            client.post(
                f"/api/tournament/{code}/pods/{pod['podId']}/result",
                json={"kind": "placement",
                      "places": [{"entrantId": s["entrantId"], "place": i}
                                 for i, s in enumerate(pod["seats"], 1)]},
            )
        client.post(f"/api/tournament/{code}/rounds/close")
        client.post(f"/api/tournament/{code}/rounds", json={})
        second = [frozenset(s["entrantId"] for s in p["seats"])
                  for p in client.get(f"/api/tournament/{code}").json()["pods"]]
        assert not set(first) & set(second), "round two repeated a pod"


class TestTimer:
    def test_start_and_extend_a_round(self, client):
        organizer(client, "hostX")
        code = host(client, settings={"roundMinutes": 50})
        add(client, code, ["t1", "t2", "t3", "t4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/timer", json={"action": "start"})
        state = client.get(f"/api/tournament/{code}").json()
        assert state["round"]["endsAt"] - state["round"]["now"] > 49 * 60
        client.post(f"/api/tournament/{code}/timer", json={"action": "extend", "minutes": 10})
        later = client.get(f"/api/tournament/{code}").json()
        assert later["round"]["endsAt"] > state["round"]["endsAt"]

    def test_extension_can_target_one_pod(self, client):
        organizer(client, "hostY")
        code = host(client)
        add(client, code, ["e1", "e2", "e3", "e4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(f"/api/tournament/{code}/timer", json={"action": "start"})
        client.post(
            f"/api/tournament/{code}/timer",
            json={"action": "extend", "minutes": 5, "podId": pod["podId"]},
        )
        state = client.get(f"/api/tournament/{code}").json()
        assert state["pods"][0]["extensionSeconds"] == 300
        assert state["round"]["endsAt"] is not None

    def test_pause_and_resume_pushes_the_deadline_out(self, client):
        organizer(client, "hostZ")
        code = host(client)
        add(client, code, ["p1", "p2", "p3", "p4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/timer", json={"action": "start"})
        client.post(f"/api/tournament/{code}/timer", json={"action": "pause"})
        assert client.get(f"/api/tournament/{code}").json()["round"]["pausedAt"] is not None
        client.post(f"/api/tournament/{code}/timer", json={"action": "resume"})
        assert client.get(f"/api/tournament/{code}").json()["round"]["pausedAt"] is None


class TestOfficialCalls:
    def test_a_player_can_call_and_staff_sees_it(self, client):
        organizer(client, "hostAA")
        code = host(client)
        add(client, code, ["o1", "o2", "o3", "o4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                    params={"token": seat_token(client, code, pod)},
                    json={"category": "rules", "note": "stack question"})
        calls = client.get(f"/api/tournament/{code}").json()["calls"]
        assert len(calls) == 1 and calls[0]["status"] == "open"

    def test_one_open_call_per_pod(self, client):
        organizer(client, "hostAB")
        code = host(client)
        add(client, code, ["o5", "o6", "o7", "o8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        first = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                            params={"token": seat_token(client, code, pod)}, json={}).json()
        again = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                            params={"token": seat_token(client, code, pod)}, json={}).json()
        assert again["callId"] == first["callId"] and again.get("alreadyOpen") is True

    def test_acknowledge_then_resolve(self, client):
        organizer(client, "hostAC")
        code = host(client)
        add(client, code, ["o9", "o10", "o11", "o12"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        call_id = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                            params={"token": seat_token(client, code, pod)}, json={}).json()["callId"]
        client.post(f"/api/tournament/{code}/calls/{call_id}/ack")
        assert client.get(f"/api/tournament/{code}").json()["calls"][0]["status"] == "acknowledged"
        client.post(f"/api/tournament/{code}/calls/{call_id}/resolve", json={"note": "ruled"})
        assert client.get(f"/api/tournament/{code}").json()["calls"] == []

    def test_calls_can_be_disabled(self, client):
        organizer(client, "hostAD")
        code = host(client, settings={"allowOfficialCalls": False})
        add(client, code, ["o13", "o14", "o15", "o16"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        assert client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call", json={}).status_code == 409


class TestPlayerView:
    def test_a_claimed_player_sees_their_pod(self, client):
        organizer(client, "hostAE")
        code = host(client)
        added = add(client, code, ["v1", "v2", "v3", "v4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]}
        ).json()["entrantToken"]
        state = client.get(f"/api/tournament/{code}", params={"token": token}).json()
        assert state["me"]["entrantId"] == added[0]["entrantId"]
        assert state["myPod"] is not None and state["myPod"]["roomCode"]
        assert state["isOrganizer"] is False

    def test_players_do_not_see_the_call_queue(self, client):
        organizer(client, "hostAF")
        code = host(client)
        add(client, code, ["v5", "v6", "v7", "v8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        assert client.get(f"/api/tournament/{code}").json()["calls"] == []

    def test_the_players_own_room_token_lets_them_walk_into_the_pod_room(self, client):
        """The whole check-in promise: claim a name, and the phone can open the
        pod's room with no code typed in between."""
        organizer(client, "hostAG")
        code = host(client)
        added = add(client, code, ["v9", "v10", "v11", "v12"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]}
        ).json()["entrantToken"]
        my_pod = client.get(f"/api/tournament/{code}", params={"token": token}).json()["myPod"]
        assert my_pod["roomToken"]
        # the token really is a seat in that room, not a placeholder
        me = client.get(
            f"/api/table/rooms/{my_pod['roomCode']}/me",
            headers={"X-Player-Token": my_pod["roomToken"]},
        )
        assert me.status_code == 200

    def test_a_room_token_never_leaks_into_the_pod_list_everyone_sees(self, client):
        """Regression: a room token is a seat credential. Exposing another
        player's would let anyone take over their seat mid-round."""
        organizer(client, "hostAH")
        code = host(client)
        added = add(client, code, ["v13", "v14", "v15", "v16"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]}
        ).json()["entrantToken"]
        state = client.get(f"/api/tournament/{code}", params={"token": token}).json()
        for pod in state["pods"]:
            assert "roomToken" not in pod
            for seat in pod["seats"]:
                assert "roomToken" not in seat and "room_token" not in seat

    def test_an_anonymous_viewer_gets_no_room_token_at_all(self, client):
        organizer(client, "hostAI")
        code = host(client)
        add(client, code, ["v17", "v18", "v19", "v20"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.cookies.clear()
        state = client.get(f"/api/tournament/{code}").json()
        assert state["myPod"] is None
        assert "roomToken" not in json.dumps(state)


class TestImportIdempotency:
    """An import adapter must be re-runnable. Design item #34."""

    def test_re_running_an_import_matches_instead_of_duplicating(self, client):
        organizer(client, "hostAJ")
        code = host(client)
        body = {"entrants": [{"name": "Ada", "externalRef": "topdeck:9f3c"},
                             {"name": "Grace", "externalRef": "topdeck:1a2b"}]}
        first = client.post(f"/api/tournament/{code}/entrants", json=body).json()
        assert len(first["added"]) == 2 and first["matched"] == []

        second = client.post(f"/api/tournament/{code}/entrants", json=body).json()
        assert second["added"] == []
        assert len(second["matched"]) == 2
        assert [e["entrantId"] for e in second["matched"]] == [e["entrantId"] for e in first["added"]]
        assert len(client.get(f"/api/tournament/{code}/roster").json()["entrants"]) == 2

    def test_an_upstream_rename_follows_rather_than_forking_the_person(self, client):
        organizer(client, "hostAK")
        code = host(client)
        client.post(f"/api/tournament/{code}/entrants",
                    json={"entrants": [{"name": "Ada", "externalRef": "topdeck:77"}]})
        client.post(f"/api/tournament/{code}/entrants",
                    json={"entrants": [{"name": "Ada L.", "externalRef": "topdeck:77"}]})
        roster = client.get(f"/api/tournament/{code}/roster").json()["entrants"]
        assert len(roster) == 1 and roster[0]["name"] == "Ada L."

    def test_identical_names_without_a_ref_stay_separate_people(self, client):
        """Names are display, not identity — two people really can share one."""
        organizer(client, "hostAL")
        code = host(client)
        r = client.post(f"/api/tournament/{code}/entrants", json={"names": ["Ada", "Ada"]}).json()
        assert len(r["added"]) == 2
        assert r["added"][0]["entrantId"] != r["added"][1]["entrantId"]

    def test_the_same_ref_can_be_reused_across_different_tournaments(self, client):
        organizer(client, "hostAM")
        a, b = host(client, name="Event A"), host(client, name="Event B")
        for c in (a, b):
            r = client.post(f"/api/tournament/{c}/entrants",
                            json={"entrants": [{"name": "Ada", "externalRef": "topdeck:9f3c"}]}).json()
            assert len(r["added"]) == 1

    def test_manual_and_imported_entrants_coexist_in_one_call(self, client):
        organizer(client, "hostAN")
        code = host(client)
        r = client.post(f"/api/tournament/{code}/entrants", json={
            "names": ["Walk-in"],
            "entrants": [{"name": "Ada", "externalRef": "topdeck:5"}],
        }).json()
        assert len(r["added"]) == 2


def _finish_pods(client, code):
    """Report a placement for every pod in the open round."""
    for pod in client.get(f"/api/tournament/{code}").json()["pods"]:
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/result", json={
            "kind": "placement",
            "places": [{"entrantId": s["entrantId"], "place": i}
                       for i, s in enumerate(pod["seats"], 1)],
        })


def _play_extra_turns(client, code, pod_id, turns=5):
    """Tap through the additional turns MTR 2.4 requires after time."""
    last = None
    for _ in range(turns):
        last = client.post(f"/api/tournament/{code}/pods/{pod_id}/turn", json={"delta": -1}).json()
    return last


class TestTimeCalled:
    def test_default_policy_draws_every_unfinished_pod(self, client):
        """MTR 2.4: a match going to time is a draw, not a life-total ranking."""
        organizer(client, "hostAO")
        code = host(client)
        add(client, code, ["t1", "t2", "t3", "t4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/rounds/time").json()
        # time called starts the additional turns; it does not decide yet
        assert r["decided"] == 0 and r["extraTurns"] == 1 and r["turns"] == 5
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        assert pod["status"] == "extra_turns" and pod["turnsRemaining"] == 5

        last = _play_extra_turns(client, code, pod["podId"])
        assert last["decided"] is True
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        assert pod["status"] == "complete"
        assert {s["place"] for s in pod["seats"]} == {1}   # all drew

    def test_highest_life_ranks_survivors_and_ties_stay_tied(self, client):
        organizer(client, "hostAP")
        code = host(client, settings={"timeCalledPolicy": "highest_life"})
        add(client, code, ["t5", "t6", "t7", "t8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        seats = q("SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
                  "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
                  (pod["podId"],)).fetchall()
        lives = [12, 30, 30, 5]
        for s, life in zip(seats, lives):
            q("UPDATE players SET life = ? WHERE token = ?", (life, s["room_token"]))

        client.post(f"/api/tournament/{code}/rounds/time")
        _play_extra_turns(client, code, pod["podId"])
        after = client.get(f"/api/tournament/{code}").json()["pods"][0]
        place = {s["entrantId"]: s["place"] for s in after["seats"]}
        by_entrant = {s["public_id"]: life for s, life in zip(seats, lives)}
        # the two players on 30 tie for first; 12 then 5 follow
        top = [e for e, l in by_entrant.items() if l == 30]
        assert place[top[0]] == place[top[1]] == 1
        assert place[[e for e, l in by_entrant.items() if l == 12][0]] == 3
        assert place[[e for e, l in by_entrant.items() if l == 5][0]] == 4

    def test_eliminated_players_rank_below_survivors(self, client):
        organizer(client, "hostAQ")
        code = host(client, settings={"timeCalledPolicy": "highest_life"})
        add(client, code, ["t9", "t10", "t11", "t12"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        seats = q("SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
                  "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
                  (pod["podId"],)).fetchall()
        # seat 4 is dead despite a high life total; it must not outrank the living
        q("UPDATE players SET life = 1 WHERE token = ?", (seats[0]["room_token"],))
        q("UPDATE players SET life = 99, eliminated = 1, eliminated_at = 500 WHERE token = ?",
          (seats[3]["room_token"],))
        client.post(f"/api/tournament/{code}/rounds/time")
        _play_extra_turns(client, code, pod["podId"])
        after = client.get(f"/api/tournament/{code}").json()["pods"][0]
        place = {s["entrantId"]: s["place"] for s in after["seats"]}
        assert place[seats[0]["public_id"]] < place[seats[3]["public_id"]]

    def test_organizer_decides_leaves_pods_awaiting_a_ruling(self, client):
        organizer(client, "hostAR")
        code = host(client, settings={"timeCalledPolicy": "organizer_decides"})
        add(client, code, ["t13", "t14", "t15", "t16"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/rounds/time").json()
        assert r["extraTurns"] == 1          # the turns are played regardless of policy
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        _play_extra_turns(client, code, pod["podId"])
        assert client.get(f"/api/tournament/{code}").json()["pods"][0]["status"] == "awaiting_result"

    def test_calling_time_never_overwrites_a_reported_result(self, client):
        organizer(client, "hostAS")
        code = host(client)
        add(client, code, ["t17", "t18", "t19", "t20"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        _finish_pods(client, code)
        before = client.get(f"/api/tournament/{code}").json()["pods"][0]["seats"]
        client.post(f"/api/tournament/{code}/rounds/time")
        after = client.get(f"/api/tournament/{code}").json()["pods"][0]["seats"]
        assert {s["entrantId"]: s["place"] for s in before} == {s["entrantId"]: s["place"] for s in after}

    def test_calling_time_with_no_round_open_is_a_conflict(self, client):
        organizer(client, "hostAT")
        code = host(client)
        assert client.post(f"/api/tournament/{code}/rounds/time").status_code == 409


class TestEndingAndReturning:
    def test_ending_freezes_standings_and_blocks_new_rounds(self, client):
        organizer(client, "hostAU")
        code = host(client)
        add(client, code, ["e1", "e2", "e3", "e4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        _finish_pods(client, code)
        client.post(f"/api/tournament/{code}/rounds/close")
        r = client.post(f"/api/tournament/{code}/end")
        assert r.status_code == 200 and len(r.json()["standings"]) == 4
        assert client.get(f"/api/tournament/{code}").json()["tournament"]["status"] == "ended"
        assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 409

    def test_cannot_end_while_a_round_is_still_open(self, client):
        organizer(client, "hostAV")
        code = host(client)
        add(client, code, ["e5", "e6", "e7", "e8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        assert client.post(f"/api/tournament/{code}/end").status_code == 409

    def test_a_dropped_player_can_be_brought_back(self, client):
        organizer(client, "hostAW")
        code = host(client)
        added = add(client, code, ["e9", "e10", "e11", "e12"])
        eid = added[0]["entrantId"]
        client.post(f"/api/tournament/{code}/entrants/{eid}/drop")
        assert next(e for e in client.get(f"/api/tournament/{code}/roster").json()["entrants"]
                    if e["entrantId"] == eid)["dropped"] is True
        client.post(f"/api/tournament/{code}/entrants/{eid}/undrop")
        assert next(e for e in client.get(f"/api/tournament/{code}/roster").json()["entrants"]
                    if e["entrantId"] == eid)["dropped"] is False
        # and they are paired again
        client.post(f"/api/tournament/{code}/rounds", json={})
        seated = {s["entrantId"] for p in client.get(f"/api/tournament/{code}").json()["pods"]
                  for s in p["seats"]}
        assert eid in seated


class TestWizardsEmail:
    def test_not_collected_by_default(self, client):
        organizer(client, "hostAX")
        code = host(client)
        added = add(client, code, ["w1", "w2", "w3", "w4"])
        client.cookies.clear()
        client.post(f"/api/tournament/{code}/claim",
                    json={"entrantId": added[0]["entrantId"], "wizardsEmail": "a@b.com"})
        stored = q("SELECT wizards_email FROM entrants WHERE public_id = ?",
                   (added[0]["entrantId"],)).fetchone()["wizards_email"]
        assert stored is None   # discarded: the organizer never asked for it

    def test_required_blocks_a_claim_without_one(self, client):
        organizer(client, "hostAY")
        code = host(client, settings={"collectWizardsEmail": "required"})
        added = add(client, code, ["w5", "w6", "w7", "w8"])
        client.cookies.clear()
        assert client.post(f"/api/tournament/{code}/claim",
                           json={"entrantId": added[0]["entrantId"]}).status_code == 422
        ok = client.post(f"/api/tournament/{code}/claim",
                         json={"entrantId": added[0]["entrantId"], "wizardsEmail": "a@b.com"})
        assert ok.status_code == 200

    def test_never_exposed_on_the_public_roster(self, client):
        organizer(client, "hostAZ")
        code = host(client, settings={"collectWizardsEmail": "optional"})
        added = add(client, code, ["w9", "w10", "w11", "w12"])
        client.cookies.clear()
        client.post(f"/api/tournament/{code}/claim",
                    json={"entrantId": added[0]["entrantId"], "wizardsEmail": "secret@b.com"})
        assert "secret@b.com" not in json.dumps(client.get(f"/api/tournament/{code}/roster").json())
        assert "secret@b.com" not in json.dumps(client.get(f"/api/tournament/{code}").json())


class TestGameSurface:
    """MTG is a profile over a generic core, not the core itself."""

    def test_the_server_advertises_its_game_profiles(self, client):
        games = client.get("/api/tournament/games").json()["games"]
        assert [g["key"] for g in games] == ["mtg"]
        mtg = games[0]
        assert mtg["defaultPodSize"] == 4 and "treachery" in mtg["modes"]
        assert mtg["publisher"] == "Wizards of the Coast"

    def test_games_route_is_not_shadowed_by_the_tournament_code_route(self, client):
        """/games must not be read as a 5-char tournament code."""
        r = client.get("/api/tournament/games")
        assert r.status_code == 200 and "games" in r.json()

    def test_defaults_come_from_the_profile_not_a_hardcoded_table(self, client):
        organizer(client, "hostBA")
        code = host(client)
        cfg = client.get(f"/api/tournament/{code}").json()["tournament"]["settings"]
        from app.games import MTG
        assert cfg["podSize"] == MTG.default_pod_size
        assert cfg["startingLife"] == MTG.resource_start
        assert cfg["roundMinutes"] == MTG.default_round_minutes
        assert cfg["timeCalledPolicy"] == MTG.time_called_policies[0]

    def test_an_unknown_game_is_rejected_with_what_is_available(self, client):
        organizer(client, "hostBB")
        r = client.post("/api/tournament",
                        json={"name": "Lorcana night", "game": "lorcana", "mode": "life"})
        assert r.status_code == 400 and "mtg" in r.json()["detail"]

    def test_a_mode_the_game_does_not_have_is_rejected(self, client):
        organizer(client, "hostBC")
        r = client.post("/api/tournament",
                        json={"name": "x", "game": "mtg", "mode": "lore-race"})
        assert r.status_code == 400

    def test_a_time_called_policy_the_game_does_not_offer_is_rejected(self, client):
        organizer(client, "hostBD")
        r = client.post("/api/tournament", json={
            "name": "x", "settings": {"timeCalledPolicy": "sudden-death"}})
        assert r.status_code == 400

    def test_the_game_is_reported_on_the_snapshot(self, client):
        organizer(client, "hostBE")
        code = host(client)
        assert client.get(f"/api/tournament/{code}").json()["tournament"]["game"] == "mtg"

    def test_the_migration_backfills_rather_than_leaving_nulls(self, client):
        """Tournaments created before profiles existed are MTG events. The
        column is NOT NULL DEFAULT 'mtg', so the migration backfilled them and
        a null is impossible — assert that rather than a fallback that can
        never fire in practice."""
        import sqlite3
        organizer(client, "hostBF")
        code = host(client)
        with pytest.raises(sqlite3.IntegrityError):
            q("UPDATE tournaments SET game = NULL WHERE code = ?", (code,))
        assert q("SELECT game FROM tournaments WHERE code = ?", (code,)).fetchone()["game"] == "mtg"

    def test_an_unrecognised_game_string_still_resolves_a_profile(self, client):
        """Defence in depth: a row written by a newer build, or a profile
        removed from the registry, must degrade rather than 500."""
        from app.games import profile_for
        assert profile_for("some-future-game").key == "mtg"
        assert profile_for(None).key == "mtg"


class TestEventStructures:
    """Presets an organizer picks from. Official tables must match the source
    document exactly; house conventions must never claim to be official."""

    def test_mtr_appendix_e_table_matches_the_published_document(self, client):
        from app.games import MTR_PREMIER
        # MTR Appendix E, "All Other Formats" column, effective 2026-02-27
        expected = {
            4: (0, 4), 8: (0, 8), 9: (5, 4), 16: (5, 4), 17: (5, 8), 32: (5, 8),
            33: (6, 8), 64: (6, 8), 65: (7, 8), 128: (7, 8), 129: (8, 8),
            226: (8, 8), 227: (9, 8), 409: (9, 8), 410: (10, 8), 5000: (10, 8),
        }
        for players, (swiss, cut) in expected.items():
            p = MTR_PREMIER.plan(players)
            assert (p["swissRounds"], p["cutTo"]) == (swiss, cut), players

    def test_small_fields_run_single_elimination_with_no_swiss(self, client):
        from app.games import MTR_PREMIER
        assert MTR_PREMIER.plan(4)["elimRounds"] == 2
        assert MTR_PREMIER.plan(8)["elimRounds"] == 3
        assert MTR_PREMIER.plan(8)["swissRounds"] == 0

    def test_limited_with_a_draft_playoff_differs_only_where_the_document_says(self, client):
        from app.games import MTR_PREMIER, MTR_PREMIER_LIMITED
        # the documented difference is the 9-16 band: 4 rounds to Top 8
        assert MTR_PREMIER_LIMITED.plan(16)["swissRounds"] == 4
        assert MTR_PREMIER_LIMITED.plan(16)["cutTo"] == 8
        for n in (17, 33, 65, 129, 227, 410):
            assert MTR_PREMIER_LIMITED.plan(n) == MTR_PREMIER.plan(n) | {
                "structure": "mtr_premier_limited"}

    def test_house_structures_are_never_marked_official(self, client):
        from app.games import MTG
        for s in MTG.structures:
            if s.key.endswith("_house"):
                assert s.official is False
                assert "convention" in s.source.lower()

    def test_a_field_below_the_minimum_is_flagged_not_guessed(self, client):
        from app.games import MTR_PREMIER
        p = MTR_PREMIER.plan(2)
        assert p["belowMinimum"] is True and p["swissRounds"] == 0

    def test_plan_uses_the_live_roster_and_counts_rounds_played(self, client):
        organizer(client, "hostBG")
        code = host(client, settings={"structure": "commander_pods_house"})
        add(client, code, [f"p{i}" for i in range(12)])
        p = client.get(f"/api/tournament/{code}/plan").json()
        assert p["players"] == 12 and p["swissRounds"] == 3 and p["cutTo"] == 4
        assert p["official"] is False
        assert p["roundsPlayed"] == 0 and p["roundsRemaining"] == 3

    def test_plan_accepts_a_hypothetical_attendance(self, client):
        organizer(client, "hostBH")
        code = host(client, settings={"structure": "mtr_premier"})
        p = client.get(f"/api/tournament/{code}/plan", params={"players": 40}).json()
        assert p["swissRounds"] == 6 and p["cutTo"] == 8 and p["official"] is True
        assert "Appendix E" in p["source"]

    def test_dropped_players_do_not_inflate_the_recommendation(self, client):
        organizer(client, "hostBI")
        code = host(client, settings={"structure": "mtr_premier"})
        added = add(client, code, [f"d{i}" for i in range(20)])
        assert client.get(f"/api/tournament/{code}/plan").json()["players"] == 20
        for e in added[:5]:
            client.post(f"/api/tournament/{code}/entrants/{e['entrantId']}/drop")
        assert client.get(f"/api/tournament/{code}/plan").json()["players"] == 15

    def test_an_unknown_structure_key_falls_back_to_the_first(self, client):
        organizer(client, "hostBJ")
        code = host(client, settings={"structure": "does-not-exist"})
        assert client.get(f"/api/tournament/{code}/plan").json()["structure"] == "mtr_premier"

    def test_structures_are_advertised_with_their_provenance(self, client):
        mtg = client.get("/api/tournament/games").json()["games"][0]
        keys = {s["key"] for s in mtg["structures"]}
        assert "mtr_premier" in keys and "commander_pods_house" in keys
        official = {s["key"]: s["official"] for s in mtg["structures"]}
        assert official["mtr_premier"] is True
        assert official["commander_pods_house"] is False
        # the multiplayer caveat must reach the UI, not just the source
        assert "no multiplayer" in mtg["notes"]["multiplayer"].lower()


class TestAdditionalTurns:
    """MTR 2.4/2.6. The app can't detect a turn passing, so the table counts
    them — which is what players already do by hand."""

    def _pod(self, client, code):
        return client.get(f"/api/tournament/{code}").json()["pods"][0]

    def test_a_pod_counts_down_and_only_then_is_decided(self, client):
        organizer(client, "hostBK")
        code = host(client)
        add(client, code, ["x1", "x2", "x3", "x4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/rounds/time")
        pod = self._pod(client, code)
        for expected in (4, 3, 2, 1):
            r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn",
                            json={"delta": -1}).json()
            assert r["turnsRemaining"] == expected and r["decided"] is False
        final = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn",
                            json={"delta": -1}).json()
        assert final["decided"] is True
        assert self._pod(client, code)["status"] == "complete"

    def test_a_mis_tap_can_be_undone(self, client):
        organizer(client, "hostBL")
        code = host(client)
        add(client, code, ["x5", "x6", "x7", "x8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/rounds/time")
        pod = self._pod(client, code)
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn", json={"delta": -1})
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn",
                        json={"delta": 1}).json()
        assert r["turnsRemaining"] == 5

    def test_turns_can_exceed_the_starting_count(self, client):
        """MTR 2.6: certain slow-play penalties add turns rather than time, and
        those are added to the end-of-match additional turns."""
        organizer(client, "hostBM")
        code = host(client)
        add(client, code, ["x9", "x10", "x11", "x12"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/rounds/time")
        pod = self._pod(client, code)
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn",
                        json={"delta": 1}).json()
        assert r["turnsRemaining"] == 6

    def test_any_player_at_the_table_may_count_a_turn(self, client):
        """A judge shouldn't have to stand at the table for five turns."""
        organizer(client, "hostBN")
        code = host(client)
        added = add(client, code, ["x13", "x14", "x15", "x16"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = self._pod(client, code)
        client.post(f"/api/tournament/{code}/rounds/time")
        client.cookies.clear()          # no organizer session at all
        token = client.post(f"/api/tournament/{code}/claim",
                            json={"entrantId": added[0]["entrantId"]}).json()["entrantToken"]
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn",
                        params={"token": token}, json={"delta": -1})
        assert r.status_code == 200 and r.json()["turnsRemaining"] == 4

    def test_counting_turns_before_time_is_called_is_a_conflict(self, client):
        organizer(client, "hostBO")
        code = host(client)
        add(client, code, ["x17", "x18", "x19", "x20"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = self._pod(client, code)
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn", json={"delta": -1})
        assert r.status_code == 409

    def test_a_pod_with_no_room_is_decided_immediately(self, client):
        """Nowhere to count turns, so don't strand the pod."""
        organizer(client, "hostBP")
        code = host(client)
        add(client, code, ["x21", "x22", "x23", "x24"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = self._pod(client, code)
        q("UPDATE pods SET room_code = NULL WHERE id = ?", (pod["podId"],))
        r = client.post(f"/api/tournament/{code}/rounds/time").json()
        assert r["decided"] == 1 and r["extraTurns"] == 0

    def test_the_room_shows_its_pod_the_round_clock(self, client):
        """Players are looking at the room, not the tournament page."""
        organizer(client, "hostBQ")
        code = host(client)
        added = add(client, code, ["x25", "x26", "x27", "x28"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/timer", json={"action": "start", "minutes": 50})
        client.cookies.clear()
        tok = client.post(f"/api/tournament/{code}/claim",
                          json={"entrantId": added[0]["entrantId"]}).json()["entrantToken"]
        my = client.get(f"/api/tournament/{code}", params={"token": tok}).json()["myPod"]
        state = client.get(f"/api/table/rooms/{my['roomCode']}/me",
                           headers={"X-Player-Token": my["roomToken"]}).json()
        tr = state["tournament"]
        assert tr["code"] == code and tr["round"] == 1
        assert tr["endsAt"] and tr["now"] and tr["endsAt"] > tr["now"]

    def test_a_per_table_extension_only_moves_that_tables_clock(self, client):
        organizer(client, "hostBR")
        code = host(client)
        add(client, code, [f"y{i}" for i in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/timer", json={"action": "start", "minutes": 50})
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        client.post(f"/api/tournament/{code}/timer",
                    json={"action": "extend", "minutes": 10, "podId": pods[0]["podId"]})
        ends = []
        for p in pods:
            seat = q("SELECT room_token FROM pod_seats WHERE pod_id = ? LIMIT 1",
                     (p["podId"],)).fetchone()
            st = client.get(f"/api/table/rooms/{p['roomCode']}/me",
                            headers={"X-Player-Token": seat["room_token"]}).json()
            ends.append(st["tournament"]["endsAt"])
        assert ends[0] - ends[1] == 600


class TestJudgeExtensions:
    """MTR 2.6 — a judge grants time, the app only suggests it."""

    def test_a_short_call_suggests_nothing(self, client):
        from app.tournaments import suggested_extension
        assert suggested_extension(0) == 0
        assert suggested_extension(59) == 0
        assert suggested_extension(60) == 0      # "more than one minute"

    def test_a_longer_call_rounds_up_to_the_minute(self, client):
        from app.tournaments import suggested_extension
        assert suggested_extension(61) == 2
        assert suggested_extension(150) == 3
        assert suggested_extension(600) == 10

    def _call(self, client, code):
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        call = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                            params={"token": seat_token(client, code, pod)}, json={}).json()
        return pod, call

    def test_the_table_gets_its_lost_time_back_automatically(self, client):
        """The round clock never stops for a judge call — the table does. The
        measured disruption is given back to that table without anyone typing
        a number."""
        organizer(client, "hostBS")
        code = host(client)
        add(client, code, ["z1", "z2", "z3", "z4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, call = self._call(client, code)
        # backdate the call so it reads as a four-minute disruption
        q("UPDATE official_calls SET created_at = unixepoch() - 250 WHERE id = ?", (call["callId"],))
        r = client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve",
                        json={"note": "ruled"}).json()
        assert r["grantedBy"] == "measured" and r["grantedMinutes"] == 5
        assert q("SELECT extension_seconds e FROM pods WHERE id = ?",
                 (pod["podId"],)).fetchone()["e"] == 300

    def test_a_call_under_a_minute_extends_nothing(self, client):
        """MTR 2.6 sets the bar at more than a minute; below it, no noise."""
        organizer(client, "hostBS2")
        code = host(client)
        add(client, code, ["z1b", "z2b", "z3b", "z4b"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, call = self._call(client, code)
        r = client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve",
                        json={"note": "quick answer"}).json()
        assert r["grantedMinutes"] == 0
        assert q("SELECT extension_seconds e FROM pods WHERE id = ?",
                 (pod["podId"],)).fetchone()["e"] == 0

    def test_a_judge_can_override_the_measurement_including_down_to_zero(self, client):
        organizer(client, "hostBS3")
        code = host(client)
        add(client, code, ["z1c", "z2c", "z3c", "z4c"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, call = self._call(client, code)
        q("UPDATE official_calls SET created_at = unixepoch() - 600 WHERE id = ?", (call["callId"],))
        r = client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve",
                        json={"extendMinutes": 0}).json()
        assert r["grantedBy"] == "judge" and r["grantedMinutes"] == 0
        assert q("SELECT extension_seconds e FROM pods WHERE id = ?",
                 (pod["podId"],)).fetchone()["e"] == 0

    def test_a_deck_check_formula_is_the_judges_to_apply(self, client):
        """Duration plus three minutes — only the judge knows it applies."""
        organizer(client, "hostBS4")
        code = host(client)
        add(client, code, ["z1d", "z2d", "z3d", "z4d"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, call = self._call(client, code)
        r = client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve",
                        json={"note": "deck check", "extendMinutes": 11}).json()
        assert r["grantedMinutes"] == 11

    def test_auto_extension_can_be_turned_off_entirely(self, client):
        organizer(client, "hostBS5")
        code = host(client, settings={"autoExtendOnCall": False})
        add(client, code, ["z1e", "z2e", "z3e", "z4e"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod, call = self._call(client, code)
        q("UPDATE official_calls SET created_at = unixepoch() - 600 WHERE id = ?", (call["callId"],))
        r = client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve", json={}).json()
        assert r["grantedBy"] == "off" and r["grantedMinutes"] == 0

    def test_the_extension_reaches_the_players_clock(self, client):
        organizer(client, "hostBS6")
        code = host(client)
        add(client, code, ["z1f", "z2f", "z3f", "z4f"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        client.post(f"/api/tournament/{code}/timer", json={"action": "start", "minutes": 50})
        pod, call = self._call(client, code)
        seat = q("SELECT room_token FROM pod_seats WHERE pod_id = ? LIMIT 1",
                 (pod["podId"],)).fetchone()
        before = client.get(f"/api/table/rooms/{pod['roomCode']}/me",
                            headers={"X-Player-Token": seat["room_token"]}).json()["tournament"]["endsAt"]
        q("UPDATE official_calls SET created_at = unixepoch() - 250 WHERE id = ?", (call["callId"],))
        client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve", json={})
        after = client.get(f"/api/table/rooms/{pod['roomCode']}/me",
                           headers={"X-Player-Token": seat["room_token"]}).json()["tournament"]["endsAt"]
        assert after - before == 300

    def test_a_judge_can_grant_time_while_resolving(self, client):
        organizer(client, "hostBT")
        code = host(client)
        add(client, code, ["z5", "z6", "z7", "z8"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        call = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                            params={"token": seat_token(client, code, pod)}, json={}).json()
        r = client.post(f"/api/tournament/{code}/calls/{call['callId']}/resolve",
                        json={"note": "deck check", "extendMinutes": 7}).json()
        assert r["grantedMinutes"] == 7
        assert q("SELECT extension_seconds e FROM pods WHERE id = ?",
                 (pod["podId"],)).fetchone()["e"] == 420

    def test_the_open_call_queue_reports_how_long_it_has_waited(self, client):
        organizer(client, "hostBU")
        code = host(client)
        add(client, code, ["z9", "z10", "z11", "z12"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                    params={"token": seat_token(client, code, pod)}, json={})
        call = client.get(f"/api/tournament/{code}").json()["calls"][0]
        assert "openSeconds" in call and "suggestedMinutes" in call


class TestIdentityStaysSeparate:
    """Playing is anonymous by design. An account is voluntary everywhere, and
    claiming a spot hands out a tournament-scoped id — never the account's."""

    def test_claiming_needs_no_account_at_all(self, client):
        organizer(client, "hostBV")
        code = host(client)
        added = add(client, code, ["n1", "n2", "n3", "n4"])
        client.cookies.clear()          # nobody is signed in
        r = client.post(f"/api/tournament/{code}/claim",
                        json={"entrantId": added[0]["entrantId"]})
        assert r.status_code == 200 and r.json()["entrantToken"]

    def test_a_signed_in_player_is_not_linked_to_their_account(self, client):
        """Being signed in must not change what the tournament learns about
        you. The entrant is identified by a temporary token, and the account
        link stays empty unless a future feature asks permission."""
        organizer(client, "hostBW")
        code = host(client)
        added = add(client, code, ["n5", "n6", "n7", "n8"])
        client.cookies.clear()
        client.post("/api/account/signup",
                    json={"username": "playerBW", "password": "a good long password"})
        client.post(f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]})
        linked = q("SELECT account_id FROM entrants WHERE public_id = ?",
                   (added[0]["entrantId"],)).fetchone()["account_id"]
        assert linked is None

    def test_the_roster_never_exposes_an_account(self, client):
        organizer(client, "hostBX")
        code = host(client)
        add(client, code, ["n9", "n10", "n11", "n12"])
        body = json.dumps(client.get(f"/api/tournament/{code}/roster").json())
        assert "account" not in body.lower()


class TestEntrantIdsAreOpaque:
    """The roster is readable by anyone holding a tournament code, so the id it
    hands out must not disclose how many entrants exist platform-wide."""

    def test_ids_on_the_wire_are_not_sequential_integers(self, client):
        organizer(client, "hostBY")
        code = host(client)
        added = add(client, code, ["o1", "o2", "o3", "o4"])
        for e in added:
            assert isinstance(e["entrantId"], str)
            assert not e["entrantId"].isdigit()
        # and distinct entrants get distinct ids
        assert len({e["entrantId"] for e in added}) == 4

    def test_consecutive_entrants_ids_are_unrelated(self, client):
        """Sequential ids would let a stranger subtract two of them to learn the
        platform's total. Random ones carry no such relationship."""
        organizer(client, "hostBZ")
        code = host(client)
        added = add(client, code, [f"seq{i}" for i in range(6)])
        ids = [e["entrantId"] for e in added]
        assert len(ids) == len(set(ids))
        # no shared prefix beyond coincidence, and no ordering
        assert sorted(ids) != ids or len(set(i[:4] for i in ids)) > 1

    def test_the_internal_primary_key_never_reaches_a_client(self, client):
        organizer(client, "hostCA")
        code = host(client)
        added = add(client, code, ["p1", "p2", "p3", "p4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        internal = {r["id"] for r in q(
            "SELECT id FROM entrants WHERE tournament_code = ?", (code,)).fetchall()}
        state = client.get(f"/api/tournament/{code}").json()
        wire_ids = {s["entrantId"] for p in state["pods"] for s in p["seats"]}
        wire_ids |= {s["entrantId"] for s in state["standings"]}
        wire_ids |= {e["entrantId"] for e in
                     client.get(f"/api/tournament/{code}/roster").json()["entrants"]}
        assert wire_ids and not (wire_ids & {str(i) for i in internal})
        assert all(isinstance(i, str) for i in wire_ids)
        # the snapshot must not smuggle the internal id under another key either
        assert "publicId" not in json.dumps(state)

    def test_an_internal_id_is_rejected_where_a_public_one_belongs(self, client):
        """Posting the integer must fail, not silently address the same row."""
        organizer(client, "hostCB")
        code = host(client)
        added = add(client, code, ["q1", "q2", "q3", "q4"])
        internal = q("SELECT id FROM entrants WHERE public_id = ?",
                     (added[0]["entrantId"],)).fetchone()["id"]
        assert client.post(f"/api/tournament/{code}/claim",
                           json={"entrantId": str(internal)}).status_code == 404
        assert client.post(f"/api/tournament/{code}/entrants/{internal}/drop").status_code == 404

    def test_a_public_id_from_another_tournament_does_not_resolve(self, client):
        organizer(client, "hostCC")
        a, b = host(client, name="A"), host(client, name="B")
        mine = add(client, a, ["r1"])[0]["entrantId"]
        add(client, b, ["r2", "r3", "r4", "r5"])
        assert client.post(f"/api/tournament/{b}/claim",
                           json={"entrantId": mine}).status_code == 404


class TestPodAuthorization:
    """A pod id is a global integer and is NOT self-authorizing. Every one of
    these was exploitable before 2026-07-19; they are the same root cause."""

    def _event(self, client, user, names):
        organizer(client, user)
        code = host(client)
        add(client, code, names)
        client.post(f"/api/tournament/{code}/rounds", json={})
        return code, client.get(f"/api/tournament/{code}").json()["pods"][0]

    def test_a_stranger_cannot_count_turns_to_force_a_result(self, client):
        """Counting turns ends in a recorded result, so an anonymous caller who
        merely knows the tournament code must not be able to drive one."""
        code, pod = self._event(client, "secA", ["s1", "s2", "s3", "s4"])
        client.post(f"/api/tournament/{code}/rounds/time")
        client.cookies.clear()
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn", json={"delta": -1})
        assert r.status_code == 403
        assert client.get(f"/api/tournament/{code}").json()["pods"][0]["turnsRemaining"] == 5

    def test_a_player_at_another_table_cannot_count_this_ones_turns(self, client):
        code, _ = self._event(client, "secB", [f"t{i}" for i in range(8)])
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        client.post(f"/api/tournament/{code}/rounds/time")
        outsider = seat_token(client, code, pods[1])
        client.cookies.clear()
        r = client.post(f"/api/tournament/{code}/pods/{pods[0]['podId']}/turn",
                        params={"token": outsider}, json={"delta": -1})
        assert r.status_code == 403

    def test_a_player_at_the_table_still_can(self, client):
        code, pod = self._event(client, "secC", ["u1", "u2", "u3", "u4"])
        client.post(f"/api/tournament/{code}/rounds/time")
        tok = seat_token(client, code, pod)
        client.cookies.clear()
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/turn",
                        params={"token": tok}, json={"delta": -1})
        assert r.status_code == 200 and r.json()["turnsRemaining"] == 4

    def test_an_organizer_cannot_write_results_into_another_event(self, client):
        """require_organizer authorized the tournament; the pod was then looked
        up by global id, so an organizer of A could rule on B's pods."""
        code_a, _ = self._event(client, "secD", ["a1", "a2", "a3", "a4"])
        client.cookies.clear()
        code_b, pod_b = self._event(client, "secE", ["b1", "b2", "b3", "b4"])
        client.cookies.clear()
        organizer(client, "secD2")           # a different organizer entirely
        code_c = host(client)
        add(client, code_c, ["c1", "c2", "c3", "c4"])
        client.post(f"/api/tournament/{code_c}/rounds", json={})
        r = client.post(f"/api/tournament/{code_c}/pods/{pod_b['podId']}/result",
                        json={"kind": "draw", "places": []})
        assert r.status_code == 404
        assert q("SELECT COUNT(*) c FROM pod_results WHERE pod_id = ?",
                 (pod_b["podId"],)).fetchone()["c"] == 0

    def test_an_organizer_cannot_extend_another_events_clock(self, client):
        code_a, pod_a = self._event(client, "secF", ["d1", "d2", "d3", "d4"])
        client.cookies.clear()
        organizer(client, "secG")
        code_b = host(client)
        add(client, code_b, ["e1", "e2", "e3", "e4"])
        client.post(f"/api/tournament/{code_b}/rounds", json={})
        client.post(f"/api/tournament/{code_b}/timer", json={"action": "start", "minutes": 50})
        r = client.post(f"/api/tournament/{code_b}/timer",
                        json={"action": "extend", "minutes": 30, "podId": pod_a["podId"]})
        assert r.status_code == 404
        assert q("SELECT extension_seconds e FROM pods WHERE id = ?",
                 (pod_a["podId"],)).fetchone()["e"] == 0

    def test_only_a_player_at_the_table_may_call_an_official(self, client):
        """A call earns that table a time extension when resolved, so a
        stranger must not be able to raise one — nor aim it at someone else."""
        code, _ = self._event(client, "secH", [f"f{i}" for i in range(8)])
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        outsider = seat_token(client, code, pods[1])
        client.cookies.clear()
        anon = client.post(f"/api/tournament/{code}/pods/{pods[0]['podId']}/call", json={})
        assert anon.status_code == 403
        wrong_table = client.post(f"/api/tournament/{code}/pods/{pods[0]['podId']}/call",
                                  params={"token": outsider}, json={})
        assert wrong_table.status_code == 403

    def test_a_pod_from_another_tournament_never_resolves(self, client):
        code_a, pod_a = self._event(client, "secI", ["g1", "g2", "g3", "g4"])
        client.cookies.clear()
        code_b, _ = self._event(client, "secJ", ["h1", "h2", "h3", "h4"])
        for path, body in (("result", {"kind": "draw", "places": []}),
                           ("call", {}), ("turn", {"delta": -1})):
            r = client.post(f"/api/tournament/{code_b}/pods/{pod_a['podId']}/{path}", json=body)
            assert r.status_code in (403, 404), path


class TestRoomCodesAreNotPublished:
    """A room code lets its holder take a seat in that room, so it is a
    credential. Publishing every pod's code to anyone holding the tournament
    code let a stranger walk into any game."""

    def test_an_anonymous_viewer_gets_no_room_codes(self, client):
        organizer(client, "secK")
        code = host(client)
        add(client, code, [f"i{j}" for j in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        real = [r["room_code"] for r in q(
            "SELECT room_code FROM pods p JOIN trounds r ON r.id = p.round_id "
            "WHERE r.tournament_code = ?", (code,)).fetchall()]
        client.cookies.clear()
        body = json.dumps(client.get(f"/api/tournament/{code}").json())
        for rc in real:
            assert rc not in body

    def test_a_player_gets_their_own_table_only(self, client):
        organizer(client, "secL")
        code = host(client)
        add(client, code, [f"j{k}" for k in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pods = client.get(f"/api/tournament/{code}").json()["pods"]
        mine = q("SELECT room_code FROM pods WHERE id = ?", (pods[0]["podId"],)).fetchone()["room_code"]
        theirs = q("SELECT room_code FROM pods WHERE id = ?", (pods[1]["podId"],)).fetchone()["room_code"]
        tok = seat_token(client, code, pods[0])
        client.cookies.clear()
        state = client.get(f"/api/tournament/{code}", params={"token": tok}).json()
        assert state["myPod"]["roomCode"] == mine
        assert theirs not in json.dumps(state)

    def test_the_organizer_still_sees_every_room(self, client):
        organizer(client, "secM")
        code = host(client)
        add(client, code, [f"k{m}" for m in range(8)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        state = client.get(f"/api/tournament/{code}").json()
        assert all(p["roomCode"] for p in state["pods"])


class TestOrganizerEventList:
    """An organizer who closes the tab must be able to find their event again."""

    def test_lists_only_this_organizers_events(self, client):
        organizer(client, "listerA")
        mine = host(client, name="Mine")
        client.cookies.clear()
        organizer(client, "listerB")
        theirs = host(client, name="Theirs")
        codes = [t["code"] for t in client.get("/api/tournament/mine").json()["tournaments"]]
        assert theirs in codes and mine not in codes

    def test_requires_an_account(self, client):
        client.cookies.clear()
        assert client.get("/api/tournament/mine").status_code == 401

    def test_mine_is_not_read_as_a_tournament_code(self, client):
        """Route order matters: /{code} would otherwise swallow it."""
        organizer(client, "listerC")
        assert client.get("/api/tournament/mine").status_code == 200

    def test_carries_what_an_organizer_needs_to_choose(self, client):
        organizer(client, "listerD")
        code = host(client, name="Friday")
        add(client, code, ["m1", "m2", "m3", "m4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        row = next(t for t in client.get("/api/tournament/mine").json()["tournaments"]
                   if t["code"] == code)
        assert row["name"] == "Friday" and row["entrants"] == 4
        assert row["rounds"] == 1 and row["status"] == "running"
        assert "openCalls" in row

    def test_dropped_entrants_do_not_inflate_the_count(self, client):
        organizer(client, "listerE")
        code = host(client)
        added = add(client, code, ["n1", "n2", "n3", "n4"])
        client.post(f"/api/tournament/{code}/entrants/{added[0]['entrantId']}/drop")
        row = next(t for t in client.get("/api/tournament/mine").json()["tournaments"]
                   if t["code"] == code)
        assert row["entrants"] == 3

    def test_open_calls_surface_so_a_neglected_event_is_visible(self, client):
        organizer(client, "listerF")
        code = host(client)
        add(client, code, ["o1", "o2", "o3", "o4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/call",
                    params={"token": seat_token(client, code, pod)}, json={})
        row = next(t for t in client.get("/api/tournament/mine").json()["tournaments"]
                   if t["code"] == code)
        assert row["openCalls"] == 1


class TestRecords:
    """Standings carry a win/draw/loss record, which players read in the room."""

    def _played(self, client, user, kind="placement"):
        organizer(client, user)
        code = host(client)
        add(client, code, ["r1", "r2", "r3", "r4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        body = {"kind": kind}
        if kind == "placement":
            body["places"] = [{"entrantId": s["entrantId"], "place": i}
                              for i, s in enumerate(pod["seats"], 1)]
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/result", json=body)
        return code, pod

    def test_a_placement_gives_one_win_and_the_rest_losses(self, client):
        code, pod = self._played(client, "recA")
        rows = {s["entrantId"]: s for s in client.get(f"/api/tournament/{code}").json()["standings"]}
        first = pod["seats"][0]["entrantId"]
        assert rows[first]["wins"] == 1 and rows[first]["losses"] == 0
        for s in pod["seats"][1:]:
            assert rows[s["entrantId"]]["wins"] == 0
            assert rows[s["entrantId"]]["losses"] == 1

    def test_a_draw_is_not_counted_as_a_win_for_everyone(self, client):
        """A draw awards every seat place 1, so counting place==1 alone would
        report four winners."""
        code, pod = self._played(client, "recB", kind="draw")
        rows = {s["entrantId"]: s for s in client.get(f"/api/tournament/{code}").json()["standings"]}
        for s in pod["seats"]:
            assert rows[s["entrantId"]]["draws"] == 1
            assert rows[s["entrantId"]]["wins"] == 0
            assert rows[s["entrantId"]]["losses"] == 0

    def test_an_override_replaces_the_record_rather_than_adding_to_it(self, client):
        code, pod = self._played(client, "recC", kind="draw")
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/result", json={
            "kind": "placement",
            "places": [{"entrantId": s["entrantId"], "place": i}
                       for i, s in enumerate(pod["seats"], 1)]})
        rows = {s["entrantId"]: s for s in client.get(f"/api/tournament/{code}").json()["standings"]}
        first = pod["seats"][0]["entrantId"]
        assert rows[first]["wins"] == 1 and rows[first]["draws"] == 0
        assert rows[first]["wins"] + rows[first]["draws"] + rows[first]["losses"] == 1

    def test_an_unplayed_entrant_has_an_empty_record(self, client):
        organizer(client, "recD")
        code = host(client)
        add(client, code, ["u1", "u2", "u3", "u4"])
        for row in client.get(f"/api/tournament/{code}").json()["standings"]:
            assert (row["wins"], row["draws"], row["losses"], row["podsPlayed"]) == (0, 0, 0, 0)

    def test_the_record_always_sums_to_pods_played(self, client):
        code, _ = self._played(client, "recE")
        for row in client.get(f"/api/tournament/{code}").json()["standings"]:
            assert row["wins"] + row["draws"] + row["losses"] == row["podsPlayed"]

    def test_a_draw_with_no_places_still_awards_draw_points(self, client):
        """Regression: the organizer's Draw button sends no ordering, and every
        seat was left with no points at all — the pod read as played and worth
        nothing."""
        organizer(client, "recF")
        code = host(client, settings={"drawPoints": 1})
        add(client, code, ["d1", "d2", "d3", "d4"])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = client.get(f"/api/tournament/{code}").json()["pods"][0]
        client.post(f"/api/tournament/{code}/pods/{pod['podId']}/result", json={"kind": "draw"})
        for row in client.get(f"/api/tournament/{code}").json()["standings"]:
            assert row["points"] == 1, row["name"]
            assert row["draws"] == 1 and row["podsPlayed"] == 1
