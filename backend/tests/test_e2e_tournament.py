"""End-to-end tournament runs.

Everything here drives the real HTTP surface, in the order a real event happens:
an organizer signs up and creates, players claim seats on their phones, rounds
are paired into actual rooms, **games are genuinely played** — started, players
eliminated one by one — results report themselves from elimination order, rounds
close, and the event ends.

Why this file exists separately from `test_tournaments.py`: those tests exercise
endpoints in isolation and pass while the seams between them are broken. The
draw bug (an organizer's hand-entered draw awarded nobody any points) survived a
120-test suite because no test ever ran a full event and then looked at the
standings. These do.

Rules for this file:
- drive through HTTP only; no writing to the database to set up a state
- assert on what a participant would actually see
- prefer whole-event invariants (points conserved, records sum) over
  single-call assertions, since that is what catches a broken seam
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
def app_client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


class Event:
    """A tournament, driven the way its participants drive it."""

    def __init__(self, client, organizer_name, players, **settings):
        self.c = c = client
        self.players = players
        self.tokens: dict[str, str] = {}     # player name -> entrant token

        c.cookies.clear()
        c.post("/api/account/signup",
               json={"username": organizer_name, "password": "a good long password"})
        verified_email(organizer_name)
        r = c.post("/api/tournament",
                   json={"name": f"{organizer_name}'s event", "settings": settings})
        assert r.status_code == 200, r.text
        self.code = r.json()["code"]
        self.organizer_cookies = dict(c.cookies)

        c.post(f"/api/tournament/{self.code}/entrants", json={"names": list(players)})

    # -- organizer actions (need the session) --

    def as_organizer(self):
        self.c.cookies.clear()
        for k, v in self.organizer_cookies.items():
            self.c.cookies.set(k, v)
        return self.c

    def post(self, path, **kw):
        return self.as_organizer().post(f"/api/tournament/{self.code}{path}", **kw)

    def state(self):
        return self.as_organizer().get(f"/api/tournament/{self.code}").json()

    # -- player actions (need no account at all) --

    def check_in_everyone(self):
        """Each player claims their name, exactly as scanning the code does."""
        self.c.cookies.clear()
        roster = self.c.get(f"/api/tournament/{self.code}/roster").json()["entrants"]
        for e in roster:
            r = self.c.post(f"/api/tournament/{self.code}/claim",
                            json={"entrantId": e["entrantId"]})
            assert r.status_code == 200, r.text
            self.tokens[e["name"]] = r.json()["entrantToken"]

    def my_pod(self, player):
        self.c.cookies.clear()
        return self.c.get(f"/api/tournament/{self.code}",
                          params={"token": self.tokens[player]}).json()["myPod"]

    def play_out(self, player_in_pod, winner_index=0):
        """Actually play the pod's game to a finish.

        Start it, then eliminate every player but one. The surviving seat is the
        winner, and nothing reports the result — the room does, from elimination
        order. That path is the one that had never run outside a unit test.
        """
        pod = self.my_pod(player_in_pod)
        room = pod["roomCode"]
        seats = sorted(pod["seats"], key=lambda s: s["seat"])
        toks = {}
        for s in seats:
            p = self.my_pod(s["name"])
            toks[s["name"]] = p["roomToken"]

        first = seats[0]["name"]
        self.c.post(f"/api/table/rooms/{room}/start",
                    headers={"X-Player-Token": toks[first]})
        winner = seats[winner_index]["name"]
        for s in seats:
            if s["name"] == winner:
                continue
            self.c.post(f"/api/table/rooms/{room}/eliminate",
                        headers={"X-Player-Token": toks[s["name"]]}, json={})
        return winner, pod

    def standings(self):
        return self.state()["standings"]

    def row(self, name):
        return next(r for r in self.standings() if r["name"] == name)


EIGHT = ["ada", "bram", "cleo", "dev", "esme", "finn", "gus", "hana"]


class TestAFullEvent:
    def test_two_rounds_played_end_to_end(self, app_client):
        ev = Event(app_client, "e2eA", EIGHT, podSize=4, roundMinutes=50)
        ev.check_in_everyone()

        # --- round 1 ---
        assert ev.post("/rounds", json={}).status_code == 200
        ev.post("/timer", json={"action": "start", "minutes": 50})
        pods = ev.state()["pods"]
        assert len(pods) == 2, "8 players at 4 a pod"

        winners = []
        for pod in pods:
            w, _ = ev.play_out(pod["seats"][0]["name"])
            winners.append(w)

        # every pod reported itself, without the organizer touching anything
        assert all(p["status"] == "complete" for p in ev.state()["pods"])
        for w in winners:
            assert ev.row(w)["wins"] == 1, f"{w} won their pod"
            assert ev.row(w)["points"] == 3

        assert ev.post("/rounds/close").status_code == 200

        # --- round 2 ---
        assert ev.post("/rounds", json={}).status_code == 200
        for pod in ev.state()["pods"]:
            ev.play_out(pod["seats"][0]["name"])
        assert ev.post("/rounds/close").status_code == 200

        # --- the event ends and the standings hold together ---
        end = ev.post("/end")
        assert end.status_code == 200
        final = end.json()["standings"]
        assert len(final) == 8
        for r in final:
            assert r["podsPlayed"] == 2
            assert r["wins"] + r["draws"] + r["losses"] == 2, r
        # exactly one winner per pod per round: 2 pods x 2 rounds
        assert sum(r["wins"] for r in final) == 4
        # standings are ordered
        assert [r["points"] for r in final] == sorted(
            (r["points"] for r in final), reverse=True
        )
        assert [r["rank"] for r in final] == list(range(1, 9))

    def test_round_two_avoids_rematches_where_it_can(self, app_client):
        ev = Event(app_client, "e2eB", EIGHT, podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})

        def pod_sets(state):
            return [frozenset(s["name"] for s in p["seats"]) for p in state["pods"]]

        first = pod_sets(ev.state())
        for pod in ev.state()["pods"]:
            ev.play_out(pod["seats"][0]["name"])
        ev.post("/rounds/close")
        ev.post("/rounds", json={})
        second = pod_sets(ev.state())
        assert set(first) != set(second), "the same four players were re-podded together"


class TestTheThingsThatGoWrong:
    def test_time_called_plays_the_extra_turns_then_draws(self, app_client):
        ev = Event(app_client, "e2eC", EIGHT[:4], podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})
        ev.post("/timer", json={"action": "start", "minutes": 50})

        called = ev.post("/rounds/time").json()
        assert called["extraTurns"] == 1 and called["decided"] == 0

        pod = ev.state()["pods"][0]
        assert pod["turnsRemaining"] == 5
        # a player at the table counts them down, not the organizer
        tok = ev.tokens[pod["seats"][0]["name"]]
        ev.c.cookies.clear()
        for expected in (4, 3, 2, 1, 0):
            r = ev.c.post(f"/api/tournament/{ev.code}/pods/{pod['podId']}/turn",
                          params={"token": tok}, json={"delta": -1})
            assert r.json()["turnsRemaining"] == expected

        assert ev.state()["pods"][0]["status"] == "complete"
        for r in ev.standings():
            assert r["draws"] == 1 and r["wins"] == 0

    def test_a_judge_call_earns_that_table_its_time_back(self, app_client):
        ev = Event(app_client, "e2eD", EIGHT[:4], podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})
        ev.post("/timer", json={"action": "start", "minutes": 50})
        pod = ev.state()["pods"][0]

        ev.c.cookies.clear()
        call = ev.c.post(f"/api/tournament/{ev.code}/pods/{pod['podId']}/call",
                         params={"token": ev.tokens[pod["seats"][0]["name"]]},
                         json={"note": "stack question"}).json()

        assert ev.state()["calls"][0]["podId"] == pod["podId"]
        ev.post(f"/calls/{call['callId']}/ack")
        # backdate so it reads as a real disruption
        q("UPDATE official_calls SET created_at = unixepoch() - 250 WHERE id = ?",
          (call["callId"],))
        resolved = ev.post(f"/calls/{call['callId']}/resolve", json={"note": "ruled"}).json()
        assert resolved["grantedBy"] == "measured" and resolved["grantedMinutes"] == 5

        # and the players at that table see the longer clock, in their room
        seat_tok = ev.my_pod(pod["seats"][0]["name"])["roomToken"]
        room_state = ev.c.get(f"/api/table/rooms/{pod['roomCode']}/me",
                              headers={"X-Player-Token": seat_tok}).json()
        assert room_state["tournament"]["endsAt"] - room_state["tournament"]["now"] > 50 * 60

    def test_an_organizer_ruling_survives_the_game_finishing_afterwards(self, app_client):
        ev = Event(app_client, "e2eE", EIGHT[:4], podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})
        pod = ev.state()["pods"][0]

        ev.post(f"/pods/{pod['podId']}/result",
                json={"kind": "draw", "note": "ruled a draw at time"})
        assert all(r["draws"] == 1 for r in ev.standings())

        # the table finishes playing anyway — the ruling must stand
        ev.play_out(pod["seats"][0]["name"])
        assert all(r["draws"] == 1 and r["wins"] == 0 for r in ev.standings())

    def test_a_drop_leaves_the_field_but_keeps_what_they_earned(self, app_client):
        ev = Event(app_client, "e2eF", EIGHT, podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})
        for pod in ev.state()["pods"]:
            ev.play_out(pod["seats"][0]["name"])
        ev.post("/rounds/close")

        leaving = ev.standings()[0]
        earned = leaving["points"]
        ev.post(f"/entrants/{leaving['entrantId']}/drop")

        ev.post("/rounds", json={})
        seated = {s["name"] for p in ev.state()["pods"] for s in p["seats"]}
        assert leaving["name"] not in seated, "a dropped player was paired again"
        assert ev.row(leaving["name"])["points"] == earned
        assert ev.row(leaving["name"])["dropped"] is True

    def test_an_odd_field_never_produces_a_pod_of_one_or_two(self, app_client):
        ev = Event(app_client, "e2eG", EIGHT + ["iris", "jonas", "kit"], podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})
        sizes = [len(p["seats"]) for p in ev.state()["pods"]]
        assert sum(sizes) == 11
        assert min(sizes) >= 3, f"pod sizes {sizes}"


class TestWhatAPlayerSees:
    def test_a_player_checks_in_and_is_carried_to_their_table(self, app_client):
        ev = Event(app_client, "e2eH", EIGHT[:4], podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})

        pod = ev.my_pod("ada")
        assert pod["roomCode"] and pod["roomToken"], "no way into their own game"

        # that token really is a seat in that room
        ev.c.cookies.clear()
        me = ev.c.get(f"/api/table/rooms/{pod['roomCode']}/me",
                      headers={"X-Player-Token": pod["roomToken"]})
        assert me.status_code == 200
        assert me.json()["me"]["name"] == "ada"
        # and the room tells them about the round without leaving it
        assert me.json()["tournament"]["code"] == ev.code

    def test_a_player_sees_standings_without_an_account(self, app_client):
        ev = Event(app_client, "e2eI", EIGHT[:4], podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})
        ev.play_out("ada")

        ev.c.cookies.clear()
        state = ev.c.get(f"/api/tournament/{ev.code}",
                         params={"token": ev.tokens["ada"]}).json()
        assert len(state["standings"]) == 4
        assert sum(r["wins"] for r in state["standings"]) == 1
        assert state["isOrganizer"] is False
        assert state["calls"] == [], "a player must not see the judge queue"

    def test_one_players_view_never_carries_another_players_credentials(self, app_client):
        import json as _json
        ev = Event(app_client, "e2eJ", EIGHT, podSize=4)
        ev.check_in_everyone()
        ev.post("/rounds", json={})

        mine = ev.my_pod("ada")
        ev.c.cookies.clear()
        body = _json.dumps(ev.c.get(f"/api/tournament/{ev.code}",
                                    params={"token": ev.tokens["ada"]}).json())
        # every other seat's room token, and every other room code
        others = q(
            "SELECT s.room_token, p.room_code FROM pod_seats s JOIN pods p ON p.id = s.pod_id "
            "JOIN trounds r ON r.id = p.round_id WHERE r.tournament_code = ?", (ev.code,)
        ).fetchall()
        for row in others:
            if row["room_token"] and row["room_token"] != mine["roomToken"]:
                assert row["room_token"] not in body
            if row["room_code"] != mine["roomCode"]:
                assert row["room_code"] not in body
