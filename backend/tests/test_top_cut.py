"""The top cut: cutting the field, seeding a bracket, and running it.

Swiss decides who plays; the cut decides who wins. The rules that differ inside
a bracket are the point of most of these tests — a single-elimination pod may
not end in a draw, seeding comes from the standings and not from the pairer,
and a bye is a table nobody sits at.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.pairing import bracket_pods
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
    client.post("/api/account/signup", json={"username": username, "password": "a good long password"})
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, name="Cut Night", settings=None):
    r = client.post("/api/tournament", json={"name": name, "settings": settings or {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def state(client, code):
    return client.get(f"/api/tournament/{code}").json()


def pods(client, code):
    return state(client, code)["pods"]


def report(client, code, pod, order):
    """Rank a pod: `order` is entrant ids, winner first."""
    r = client.post(
        f"/api/tournament/{code}/pods/{pod['podId']}/result",
        json={"kind": "placement",
              "places": [{"entrantId": e, "place": i} for i, e in enumerate(order, 1)]},
    )
    assert r.status_code == 200, r.text


def play_round(client, code, pick=None):
    """Report every unfinished pod, then close. `pick` chooses each winner."""
    for pod in pods(client, code):
        if pod["status"] == "complete":
            continue          # a bye is already decided
        seats = [s["entrantId"] for s in pod["seats"]]
        winner = pick(seats) if pick else seats[0]
        report(client, code, pod, [winner] + [s for s in seats if s != winner])
    r = client.post(f"/api/tournament/{code}/rounds/close")
    assert r.status_code == 200, r.text


def swiss_round(client, code):
    assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
    play_round(client, code)


def duel_event(client, username, entrants=8):
    """A 1v1 event with one Swiss round in the books."""
    organizer(client, username)
    code = host(client, settings={"podSize": 2})
    added = add(client, code, [f"{username}-{i}" for i in range(entrants)])
    swiss_round(client, code)
    return code, added


def cut(client, code, size=None, expect=200):
    r = client.post(f"/api/tournament/{code}/cut", json={} if size is None else {"size": size})
    assert r.status_code == expect, r.text
    return r.json()


class TestBracketPairing:
    """Pure seeding, no database: the shape of the bracket itself."""

    def test_a_duel_bracket_is_the_published_one(self):
        """MTR Appendix E pairs 1v8, 2v7, 3v6, 4v5."""
        assert [p.seats for p in bracket_pods(list(range(1, 9)), 2)] == [
            [1, 8], [2, 7], [3, 6], [4, 5]
        ]

    def test_pods_take_a_band_of_the_field_each(self):
        """The same rule at four to a table: no pod is all top seeds."""
        assert [p.seats for p in bracket_pods(list(range(1, 9)), 4)] == [
            [1, 4, 5, 8], [2, 3, 6, 7]
        ]

    def test_a_remainder_becomes_byes_for_the_seeds_who_earned_them(self):
        assert [p.seats for p in bracket_pods([1, 2, 3, 4, 5], 2)] == [[1], [2, 5], [3, 4]]
        assert [p.seats for p in bracket_pods([1, 2, 3, 4, 5, 6], 4)] == [[1], [2], [3, 4, 5, 6]]

    def test_a_short_field_is_one_table(self):
        assert [p.seats for p in bracket_pods([1, 2, 3], 4)] == [[1, 2, 3]]

    def test_a_decided_bracket_pairs_nothing(self):
        assert bracket_pods([7], 2) == []
        assert bracket_pods([], 4) == []


class TestMakingTheCut:
    def test_the_cut_seeds_from_the_standings(self, client):
        code, _ = duel_event(client, "cutA")
        standing = [r["entrantId"] for r in state(client, code)["standings"]]
        body = cut(client, code, 4)
        assert body["cutTo"] == 4
        assert [s["entrantId"] for s in body["seeds"]] == standing[:4]
        assert [s["seed"] for s in body["seeds"]] == [1, 2, 3, 4]

    def test_the_cut_opens_the_first_bracket_round(self, client):
        code, _ = duel_event(client, "cutB")
        body = cut(client, code, 4)
        assert body["kind"] == "elimination" and body["pods"] == 2
        after = state(client, code)
        assert after["round"]["number"] == 2 and after["round"]["kind"] == "elimination"
        assert after["tournament"]["status"] == "running"
        seated = {s["entrantId"] for p in after["pods"] for s in p["seats"]}
        assert seated == {s["entrantId"] for s in body["seeds"]}, "only the cut plays on"

    def test_the_size_defaults_to_what_the_structure_recommends(self, client):
        """The number GET /plan has been advising all day, now acted on."""
        organizer(client, "cutC")
        code = host(client)                      # pods of four: the house structure
        add(client, code, [f"c{i}" for i in range(12)])
        swiss_round(client, code)
        plan = client.get(f"/api/tournament/{code}/plan").json()
        body = cut(client, code)
        assert plan["cutTo"] == 4 and body["cutTo"] == 4

    def test_a_structure_with_no_cut_needs_an_explicit_size(self, client):
        organizer(client, "cutD")
        code = host(client, settings={"structure": "commander_swiss_only_house"})
        add(client, code, [f"d{i}" for i in range(8)])
        swiss_round(client, code)
        r = client.post(f"/api/tournament/{code}/cut", json={})
        assert r.status_code == 409 and "no cut" in r.json()["detail"]
        assert cut(client, code, 4)["cutTo"] == 4

    def test_a_cut_needs_standings_to_seed_from(self, client):
        organizer(client, "cutE")
        code = host(client, settings={"podSize": 2})
        add(client, code, [f"e{i}" for i in range(8)])
        r = client.post(f"/api/tournament/{code}/cut", json={"size": 4})
        assert r.status_code == 409 and "play a round first" in r.json()["detail"]

    def test_a_cut_will_not_interrupt_an_open_round(self, client):
        code, _ = duel_event(client, "cutF")
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/cut", json={"size": 4})
        assert r.status_code == 409 and "close the current round" in r.json()["detail"]

    def test_a_dropped_entrant_loses_their_slot_to_the_next_player_up(self, client):
        code, _ = duel_event(client, "cutG")
        standing = [r["entrantId"] for r in state(client, code)["standings"]]
        client.post(f"/api/tournament/{code}/entrants/{standing[0]}/drop")
        seeds = [s["entrantId"] for s in cut(client, code, 4)["seeds"]]
        assert standing[0] not in seeds
        assert seeds == standing[1:5], "everyone below moves up a seat"

    def test_a_cut_larger_than_the_field_takes_the_whole_field(self, client):
        code, _ = duel_event(client, "cutH", entrants=6)
        assert cut(client, code, 8)["cutTo"] == 6

    def test_a_mis_sized_cut_can_be_redrawn_before_anyone_plays(self, client):
        code, _ = duel_event(client, "cutI")
        cut(client, code, 4)
        redrawn = cut(client, code, 8)
        assert redrawn["cutTo"] == 8
        after = state(client, code)
        assert after["tournament"]["roundCount"] == 2, "a re-cut is not a new round"
        assert len(after["pods"]) == 4
        assert after["cut"]["cutTo"] == 8

    def test_a_played_cut_cannot_be_redrawn(self, client):
        code, _ = duel_event(client, "cutJ")
        cut(client, code, 4)
        pod = pods(client, code)[0]
        report(client, code, pod, [s["entrantId"] for s in pod["seats"]])
        r = client.post(f"/api/tournament/{code}/cut", json={"size": 8})
        assert r.status_code == 409 and "already been played" in r.json()["detail"]

    def test_a_bracket_under_way_cannot_be_recut(self, client):
        """Re-seeding from Swiss now would resurrect the people it eliminated."""
        code, _ = duel_event(client, "cutM")
        cut(client, code, 8)
        play_round(client, code)
        client.post(f"/api/tournament/{code}/rounds", json={})   # semis, unplayed
        r = client.post(f"/api/tournament/{code}/cut", json={"size": 4})
        assert r.status_code == 409 and "already been played" in r.json()["detail"]

    def test_only_the_organizer_can_cut(self, client):
        code, _ = duel_event(client, "cutK")
        organizer(client, "cutK-stranger")
        assert client.post(f"/api/tournament/{code}/cut", json={"size": 4}).status_code == 403

    def test_a_cut_below_two_is_not_a_cut(self, client):
        code, _ = duel_event(client, "cutL")
        assert client.post(f"/api/tournament/{code}/cut", json={"size": 1}).status_code == 400


class TestRunningTheBracket:
    def test_every_round_halves_the_field_down_to_a_champion(self, client):
        code, _ = duel_event(client, "runA")
        cut(client, code, 8)
        assert len(pods(client, code)) == 4
        play_round(client, code)
        assert client.post(f"/api/tournament/{code}/rounds", json={}).json()["pods"] == 2
        play_round(client, code)
        assert client.post(f"/api/tournament/{code}/rounds", json={}).json()["pods"] == 1
        final = pods(client, code)[0]
        winner = final["seats"][0]["entrantId"]
        report(client, code, final, [s["entrantId"] for s in final["seats"]])
        client.post(f"/api/tournament/{code}/rounds/close")

        after = state(client, code)
        assert after["cut"]["champion"] == winner
        assert [s["alive"] for s in after["cut"]["seeds"]].count(True) == 1
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 409 and "already decided" in r.json()["detail"]

    def test_the_bracket_is_fixed_not_reseeded(self, client):
        """MTR Appendix E's bracket rewards nobody for an upset: the winner of
        1v8 meets the winner of 4v5 whoever those turn out to be."""
        code, _ = duel_event(client, "runB")
        seeds = [s["entrantId"] for s in cut(client, code, 8)["seeds"]]
        quarters = pods(client, code)
        assert [[s["entrantId"] for s in p["seats"]] for p in quarters] != []
        # the underdog takes the top table; everyone else holds serve
        winners = []
        for pod in quarters:
            members = [s["entrantId"] for s in pod["seats"]]
            best = min(members, key=seeds.index)
            worst = max(members, key=seeds.index)
            winner = worst if seeds.index(best) == 0 else best
            winners.append(winner)
            report(client, code, pod, [winner] + [m for m in members if m != winner])
        client.post(f"/api/tournament/{code}/rounds/close")
        client.post(f"/api/tournament/{code}/rounds", json={})

        semis = [{s["entrantId"] for s in p["seats"]} for p in pods(client, code)]
        assert semis == [{winners[0], winners[3]}, {winners[1], winners[2]}]
        reseeded = sorted(winners, key=seeds.index)
        assert semis != [{reseeded[0], reseeded[3]}, {reseeded[1], reseeded[2]}]

    def test_an_odd_bracket_gives_the_top_seeds_a_bye(self, client):
        code, _ = duel_event(client, "runC")
        body = cut(client, code, 5)
        assert body["byes"] == 1 and body["pods"] == 3
        drawn = pods(client, code)
        top = [s["entrantId"] for s in body["seeds"]][0]
        assert [s["entrantId"] for s in drawn[0]["seats"]] == [top]
        assert drawn[0]["status"] == "complete", "a bye is not a game to be played"
        assert drawn[0]["roomCode"] is None, "a bye needs no room"

        # the round closes on the two played tables alone, and the bye advances
        play_round(client, code)
        assert client.post(f"/api/tournament/{code}/rounds", json={}).json()["remaining"] == 3
        assert top in {s["entrantId"] for p in pods(client, code) for s in p["seats"]}

    def test_a_bye_scores_like_the_win_it_stands_in_for(self, client):
        code, _ = duel_event(client, "runD")
        top = cut(client, code, 5)["seeds"][0]["entrantId"]
        before = next(r for r in state(client, code)["standings"] if r["entrantId"] == top)
        assert before["points"] == 3 + 3, "the Swiss win plus the bye"

    def test_someone_who_goes_home_is_out_of_the_bracket(self, client):
        """A cut is a commitment to keep playing. Their table does not wait."""
        code, _ = duel_event(client, "runE")
        cut(client, code, 8)
        play_round(client, code)
        survivors = {s["entrantId"] for s in state(client, code)["cut"]["seeds"] if s["alive"]}
        assert len(survivors) == 4
        gone = sorted(survivors)[0]
        client.post(f"/api/tournament/{code}/entrants/{gone}/drop")

        assert client.post(f"/api/tournament/{code}/rounds", json={}).json()["remaining"] == 3
        seated = {s["entrantId"] for p in pods(client, code) for s in p["seats"]}
        assert seated == survivors - {gone}
        assert state(client, code)["cut"]["seeds"], "the bracket is still readable"

    def test_a_bracket_cannot_be_rerolled(self, client):
        code, _ = duel_event(client, "runF")
        cut(client, code, 4)
        r = client.post(f"/api/tournament/{code}/rounds", json={"reroll": True})
        assert r.status_code == 409 and "seeded" in r.json()["detail"]

    def test_a_pod_with_no_single_winner_stops_the_bracket(self, client):
        """A ruled draw is a legal Swiss result and an impossible bracket one."""
        code, _ = duel_event(client, "runG")
        cut(client, code, 4)
        drawn = pods(client, code)[0]
        client.post(
            f"/api/tournament/{code}/pods/{drawn['podId']}/result",
            json={"kind": "draw", "note": "both ran out of time"},
        )
        other = pods(client, code)[1]
        report(client, code, other, [s["entrantId"] for s in other["seats"]])
        assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 409 and "no single winner" in r.json()["detail"]

    def test_the_snapshot_carries_the_bracket_for_everyone(self, client):
        code, _ = duel_event(client, "runH")
        assert state(client, code)["cut"] is None, "no cut, nothing to show"
        seeds = cut(client, code, 4)["seeds"]
        client.cookies.clear()                      # an anonymous spectator
        shown = state(client, code)["cut"]
        assert shown["cutTo"] == 4 and shown["champion"] is None
        assert [s["entrantId"] for s in shown["seeds"]] == [s["entrantId"] for s in seeds]
        assert all(s["alive"] for s in shown["seeds"])


class TestTimeCalledInTheCut:
    """MTR 2.4 says opposite things in Swiss and in a bracket, and the profile
    is where that is written down."""

    def _lives(self, client, code, pod, lives):
        seats = q(
            "SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
            "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
            (pod["podId"],),
        ).fetchall()
        for s, life in zip(seats, lives):
            q("UPDATE players SET life = ? WHERE token = ?", (life, s["room_token"]))
        return [s["public_id"] for s in seats]

    def _run_out_the_clock(self, client, code, pod_id):
        client.post(f"/api/tournament/{code}/rounds/time")
        last = None
        for _ in range(10):
            last = client.post(f"/api/tournament/{code}/pods/{pod_id}/turn", json={"delta": -1}).json()
            if last.get("decided"):
                break
        return last

    def test_life_decides_a_bracket_pod_although_swiss_would_draw(self, client):
        code, _ = duel_event(client, "timeA")
        assert state(client, code)["tournament"]["settings"]["timeCalledPolicy"] == "draw_all"
        cut(client, code, 4)
        pod = pods(client, code)[0]
        ids = self._lives(client, code, pod, [17, 4])
        self._run_out_the_clock(client, code, pod["podId"])
        after = next(p for p in pods(client, code) if p["podId"] == pod["podId"])
        place = {s["entrantId"]: s["place"] for s in after["seats"]}
        assert after["status"] == "complete"
        assert place[ids[0]] == 1 and place[ids[1]] == 2, "a bracket may not end in a draw"

    def test_a_dead_level_bracket_pod_waits_for_a_person(self, client):
        code, _ = duel_event(client, "timeB")
        cut(client, code, 4)
        pod = pods(client, code)[0]
        self._lives(client, code, pod, [9, 9])
        self._run_out_the_clock(client, code, pod["podId"])
        after = next(p for p in pods(client, code) if p["podId"] == pod["podId"])
        assert after["status"] == "awaiting_result"
        assert all(s["place"] is None for s in after["seats"]), "nothing was invented"

    def test_swiss_still_draws_at_time(self, client):
        """The cut changes the ruling; it must not change it retroactively."""
        organizer(client, "timeC")
        code = host(client, settings={"podSize": 2})
        add(client, code, [f"tc{i}" for i in range(4)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        pod = pods(client, code)[0]
        self._lives(client, code, pod, [30, 2])
        self._run_out_the_clock(client, code, pod["podId"])
        after = next(p for p in pods(client, code) if p["podId"] == pod["podId"])
        assert {s["place"] for s in after["seats"]} == {1}, "MTR 2.4: Swiss draws"

    def test_an_organizer_who_rules_every_pod_still_does_in_the_cut(self, client):
        organizer(client, "timeD")
        code = host(client, settings={"podSize": 2, "timeCalledPolicy": "organizer_decides"})
        add(client, code, [f"td{i}" for i in range(8)])
        assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
        for pod in pods(client, code):
            report(client, code, pod, [s["entrantId"] for s in pod["seats"]])
        client.post(f"/api/tournament/{code}/rounds/close")
        cut(client, code, 4)
        pod = pods(client, code)[0]
        self._lives(client, code, pod, [22, 1])
        self._run_out_the_clock(client, code, pod["podId"])
        after = next(p for p in pods(client, code) if p["podId"] == pod["podId"])
        assert after["status"] == "awaiting_result"


class TestProfileSaysSo:
    def test_the_profile_names_the_single_elimination_policy(self):
        from app.games import MTG

        # the profile-neutral spelling the time-called policies were renamed to
        assert MTG.elimination_time_policy == "highest_resource"
        assert MTG.elimination_time_policy in MTG.time_called_policies
        assert "highest life" in MTG.notes["singleElimination"]

    def test_the_server_advertises_it(self, client):
        mtg = client.get("/api/tournament/games").json()["games"][0]
        assert mtg["eliminationTimePolicy"] == "highest_resource"

    def test_a_game_with_no_such_rule_would_not_get_one_invented(self):
        """The field defaults to None, and None means 'ask a human'."""
        from app.games import GameProfile

        blank = GameProfile(
            key="x", name="X", publisher="Y", default_pod_size=4, default_round_minutes=50,
            resource="points", resource_start=0, resource_direction="up", resource_goal=10,
        )
        assert blank.elimination_time_policy is None
