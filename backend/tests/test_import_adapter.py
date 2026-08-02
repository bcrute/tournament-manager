"""The import adapter, and the four places another system's shape is not ours.

§9 of the API contract says an import should be a field rename rather than a
translation layer, and then lists the four fields where that is a lie: a single
winner instead of an ordering, a draw written into an id, byes folded into a
pseudo-table, and a round number that is sometimes a phrase. Those four
mappings are most of this file.

The fifth thing under test is the direction. Imports are one-way — their API
cannot accept results — and an organizer who assumes otherwise will report a
whole event here and wonder why the other site never updated.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.importers import ImportProblem, TopDeckAdapter, adapter_for, known_sources
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
    client.post("/api/account/signup",
                json={"username": username, "password": "a good long password"})
    verified_email(username)
    return client


def host(client, name="Imported Night"):
    """A duel event: TopDeck's tables seat two, so ours do too."""
    r = client.post("/api/tournament",
                    json={"name": name, "settings": {"podSize": 2}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


# --- a TopDeck-shaped payload, built the way their export reads ---

PEOPLE = [(f"t{i}", n) for i, n in enumerate(
    ["Ada", "Grace", "Alan", "Edsger", "Barbara", "Donald", "Radia", "Leslie", "Katherine"], 1)]


def person(idx):
    pid, name = PEOPLE[idx]
    return {"id": pid, "name": name}


def table(number, a, b, winner=None):
    """One of their tables. `winner` is an index into PEOPLE, or the string
    they use for a drawn match, or None for a table with no result yet."""
    row = {"table": number, "players": [person(a), person(b)]}
    if winner == "Draw":
        row["winner"] = "Draw"
        row["winner_id"] = "Draw"
    elif winner is not None:
        row["winner"] = PEOPLE[winner][1]
        row["winner_id"] = PEOPLE[winner][0]
    return row


def payload(rounds, people=PEOPLE):
    return {
        "TID": "abc123",
        "tournamentName": "Friday Duels",
        "standings": [{"id": pid, "name": name} for pid, name in people],
        "rounds": rounds,
    }


#: round 1, four tables plus the row TopDeck puts a bye in
ROUND_ONE = {
    "round": 1,
    "tables": [
        table(1, 0, 1, winner=0),
        table(2, 2, 3, winner=2),
        table(3, 4, 5, winner=4),
        table(4, 6, 7, winner=6),
        {"table": "Byes", "players": [person(8)]},
    ],
}

#: round 2, one of which went to time
ROUND_TWO = {
    "round": "2",
    "tables": [
        table(1, 0, 2, winner=0),
        table(2, 4, 6, winner="Draw"),
        table(3, 1, 3, winner=1),
        table(4, 5, 7, winner=5),
    ],
}

#: the cut, labelled the way they label it
TOP_EIGHT = {
    "round": "Top 8",
    "tables": [
        table(1, 0, 7, winner=0),
        table(2, 3, 4, winner=3),
        table(3, 1, 6, winner=1),
        table(4, 2, 5, winner=2),
    ],
}


def do_import(client, code, body, expect=200):
    r = client.post(f"/api/tournament/{code}/import", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def imported(client, code, rounds):
    return do_import(client, code, {"source": "topdeck", "payload": payload(rounds)})


def read(rounds, people=PEOPLE):
    return TopDeckAdapter().read(payload(rounds, people))


class TestTopDeckMappings:
    """The four rows of §9's 'where we deliberately differ' table."""

    def test_a_single_winner_becomes_an_ordered_places_list(self):
        """Their model has one winner and no ordering. Ours is places[] — so
        the winner is first and everyone else is jointly second, which is all
        the source actually recorded. Spreading them 2..N would be fiction."""
        pod = read([ROUND_ONE]).rounds[0].pods[0]
        assert pod.kind == "placement"
        assert [(s.ref, s.place) for s in pod.seats] == [
            ("topdeck:t1", 1), ("topdeck:t2", 2)
        ]

    def test_a_draw_in_the_id_field_becomes_a_kind(self):
        """`winner_id: "Draw"` is a magic string in an id field. It must not
        survive the boundary — no client should ever compare an id to "Draw"."""
        rnd = read([ROUND_TWO]).rounds[0]
        drawn = next(p for p in rnd.pods if p.kind == "draw")
        assert [s.place for s in drawn.seats] == [1, 1]
        assert "Draw" not in json.dumps([s.ref for p in rnd.pods for s in p.seats])

    def test_a_byes_row_becomes_one_bye_pod_per_player(self):
        """Their "Byes" is a list of people who sat out, folded into one row
        because their model has nowhere else to put it. A bye here is a pod of
        one, so the row expands rather than seating everyone together."""
        pods = read([ROUND_ONE]).rounds[0].pods
        byes = [p for p in pods if p.kind == "bye"]
        assert len(byes) == 1
        assert [s.ref for s in byes[0].seats] == ["topdeck:t9"]
        assert all(len(p.seats) == 1 for p in byes)

    def test_two_people_in_the_byes_row_are_two_byes_not_a_table(self):
        rnd = read([{"round": 1, "tables": [
            {"table": "Byes", "players": [person(0), person(1)]}
        ]}]).rounds[0]
        assert len(rnd.pods) == 2 and all(p.kind == "bye" for p in rnd.pods)

    def test_top_8_becomes_an_integer_round_number_and_a_cut_flag(self):
        """The two halves of the mapping: `number` stays an integer that
        continues the event, and `kind` carries what the label was saying."""
        rounds = read([ROUND_ONE, ROUND_TWO, TOP_EIGHT]).rounds
        assert [r.number for r in rounds] == [1, 2, 3]
        assert [r.kind for r in rounds] == ["swiss", "swiss", "elimination"]
        assert rounds[2].cut_to == 8

    def test_a_named_final_is_a_bracket_round_too(self):
        rounds = read([ROUND_ONE, {"round": "Finals", "tables": [table(1, 0, 1, winner=0)]}]).rounds
        assert (rounds[1].number, rounds[1].kind, rounds[1].cut_to) == (2, "elimination", 2)

    def test_the_winner_name_beside_the_id_is_discarded(self):
        """Results denormalized onto display names, which change. A table that
        names a winner but gives no id has no result — it is not ruled from a
        name, because that would make names identity."""
        row = table(1, 0, 1)
        row["winner"] = PEOPLE[0][1]        # a name, and nothing else
        pod = read([{"round": 1, "tables": [row]}]).rounds[0].pods[0]
        assert pod.kind is None
        assert all(s.place is None for s in pod.seats)

    def test_a_player_without_an_id_is_refused(self):
        with pytest.raises(ImportProblem) as e:
            read([{"round": 1, "tables": [
                {"table": 1, "players": [{"name": "Ada"}, person(1)]}
            ]}])
        assert "never a name" in str(e.value)

    def test_an_unrecognised_round_label_is_refused(self):
        """A bracket round mistaken for Swiss is invisible afterwards and pairs
        the next round from standings, so the adapter stops instead."""
        with pytest.raises(ImportProblem):
            read([{"round": "Play-in", "tables": [table(1, 0, 1, winner=0)]}])

    def test_a_winner_who_is_not_seated_is_refused(self):
        row = table(1, 0, 1, winner=0)
        row["winner_id"] = "t7"
        with pytest.raises(ImportProblem) as e:
            read([{"round": 1, "tables": [row]}])
        assert "not seated" in str(e.value)

    def test_a_player_seated_but_missing_from_the_standings_still_becomes_an_entrant(self):
        event = read([ROUND_ONE], people=PEOPLE[:2])
        assert len(event.entrants) == len(PEOPLE)


class TestTheAdapterBoundary:
    """One interface, one implementation, and no assumption it is the only one."""

    def test_the_interface_reads_and_never_writes(self):
        """Imports are one-way structurally, not by policy: there is nothing on
        an adapter that could send anything back."""
        for name in ("write", "push", "sync", "post", "send", "export"):
            assert not hasattr(TopDeckAdapter(), name)
        assert callable(TopDeckAdapter().read)

    def test_every_source_says_it_is_one_way(self):
        sources = known_sources()
        assert sources and all(s["oneWay"] and not s["acceptsResults"] for s in sources)

    def test_an_unknown_source_is_never_guessed_at(self):
        """Reading an event through the wrong adapter is worse than not
        importing it, so there is no fallback to the only one we have."""
        assert adapter_for("moxfield") is None
        assert adapter_for(None) is None

    def test_the_sources_endpoint_states_the_direction(self, client):
        organizer(client, "importOrgA")
        body = client.get("/api/tournament/import/sources").json()
        assert body["oneWay"] is True
        assert "cannot accept results" in body["note"]
        assert "topdeck" in {s["key"] for s in body["sources"]}


class TestImportingAnEvent:
    def test_entrants_arrive_tagged_with_an_external_ref(self, client):
        organizer(client, "importOrgB")
        code = host(client)
        out = imported(client, code, [ROUND_ONE])
        assert len(out["entrants"]["added"]) == len(PEOPLE)
        assert {e["externalRef"] for e in out["entrants"]["added"]} == {
            f"topdeck:{pid}" for pid, _ in PEOPLE
        }

    def test_re_importing_matches_instead_of_duplicating(self, client):
        """Their export is the whole event every time, so a re-run re-sends
        rounds we already have. It must be safe: the same people are matched,
        and a round already here is skipped rather than replayed."""
        organizer(client, "importOrgC")
        code = host(client)
        imported(client, code, [ROUND_ONE])
        again = imported(client, code, [ROUND_ONE])
        assert again["entrants"]["added"] == []
        assert len(again["entrants"]["matched"]) == len(PEOPLE)
        assert again["rounds"] == [dict(again["rounds"][0], skipped=True)]
        roster = client.get(f"/api/tournament/{code}/roster").json()["entrants"]
        assert len(roster) == len(PEOPLE)
        assert q("SELECT COUNT(*) c FROM trounds WHERE tournament_code = ?",
                 (code,)).fetchone()["c"] == 1

    def test_a_re_run_picks_up_only_the_rounds_that_are_new(self, client):
        organizer(client, "importOrgD")
        code = host(client)
        imported(client, code, [ROUND_ONE])
        out = imported(client, code, [ROUND_ONE, ROUND_TWO])
        assert [(r["number"], r["skipped"]) for r in out["rounds"]] == [(1, True), (2, False)]
        assert len(client.get(f"/api/tournament/{code}/roster").json()["entrants"]) == len(PEOPLE)
        assert client.get(f"/api/tournament/{code}").json()["round"]["number"] == 2

    def test_an_import_never_links_an_entrant_to_an_account(self, client):
        """The organizer is signed in — they have to be — and nine people are
        created by their request. None of them is anybody's account."""
        organizer(client, "importOrgE")
        code = host(client)
        out = imported(client, code, [ROUND_ONE])
        for e in out["entrants"]["added"]:
            row = q("SELECT account_id FROM entrants WHERE public_id = ?",
                    (e["entrantId"],)).fetchone()
            assert row["account_id"] is None

    def test_a_drawn_table_scores_as_a_draw(self, client):
        organizer(client, "importOrgF")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO])
        history = client.get(f"/api/tournament/{code}/rounds/2").json()
        drawn = next(p for p in history["pods"] if p["result"]["kind"] == "draw")
        assert {s["points"] for s in drawn["seats"]} == {1}     # drawPoints, both seats
        assert {s["place"] for s in drawn["seats"]} == {1}

    def test_a_bye_scores_as_a_bye(self, client):
        organizer(client, "importOrgG")
        code = host(client)
        imported(client, code, [ROUND_ONE])
        history = client.get(f"/api/tournament/{code}/rounds/1").json()
        bye = next(p for p in history["pods"] if p["result"]["kind"] == "bye")
        assert len(bye["seats"]) == 1
        assert bye["seats"][0]["points"] == 3                   # byeScoring: win

    def test_a_result_can_be_read_back_as_the_type_it_was_written(self, client):
        """A client that can write a kind it can never read back has been sold
        a type it cannot use."""
        organizer(client, "importOrgH")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO])
        kinds = {p["result"]["kind"]
                 for n in (1, 2)
                 for p in client.get(f"/api/tournament/{code}/rounds/{n}").json()["pods"]}
        assert kinds == {"placement", "draw", "bye"}
        rows = client.get(f"/api/tournament/{code}/export",
                          params={"what": "results"}).json()["results"]
        assert {r["source"] for r in rows} == {"import"}

    def test_imported_results_move_the_standings(self, client):
        organizer(client, "importOrgI")
        code = host(client)
        imported(client, code, [ROUND_ONE])
        standings = client.get(f"/api/tournament/{code}").json()["standings"]
        by_name = {s["name"]: s["points"] for s in standings}
        assert by_name["Ada"] == 3          # won her table
        assert by_name["Grace"] == 0        # lost it
        assert by_name["Katherine"] == 3    # the bye

    def test_the_response_says_imports_are_one_way(self, client):
        organizer(client, "importOrgJ")
        code = host(client)
        out = imported(client, code, [ROUND_ONE])
        assert out["oneWay"] is True
        assert "one-way" in out["note"].lower()
        assert out["sourceName"] == "TopDeck Tournaments V2"

    def test_a_dry_run_writes_nothing(self, client):
        organizer(client, "importOrgK")
        code = host(client)
        out = do_import(client, code, {"source": "topdeck",
                                       "payload": payload([ROUND_ONE, ROUND_TWO]),
                                       "dryRun": True})
        assert out["dryRun"] is True and out["oneWay"] is True
        assert len(out["entrants"]["added"]) == len(PEOPLE)
        assert [r["number"] for r in out["rounds"]] == [1, 2]
        assert client.get(f"/api/tournament/{code}/roster").json()["entrants"] == []
        assert client.get(f"/api/tournament/{code}").json()["round"] is None

    def test_a_dry_run_of_a_re_run_says_who_is_already_here(self, client):
        organizer(client, "importOrgX")
        code = host(client)
        imported(client, code, [ROUND_ONE])
        out = do_import(client, code, {"source": "topdeck",
                                       "payload": payload([ROUND_ONE, ROUND_TWO]),
                                       "dryRun": True})
        assert out["entrants"]["added"] == []
        assert all(e["entrantId"] for e in out["entrants"]["matched"])
        assert [(r["number"], r["skipped"]) for r in out["rounds"]] == [(1, True), (2, False)]
        assert q("SELECT COUNT(*) c FROM trounds WHERE tournament_code = ?",
                 (code,)).fetchone()["c"] == 1

    def test_an_unknown_source_is_refused_by_the_endpoint(self, client):
        organizer(client, "importOrgL")
        code = host(client)
        out = do_import(client, code, {"source": "moxfield", "payload": {}}, expect=400)
        assert "topdeck" in out["detail"]

    def test_only_the_organizer_may_import(self, client):
        organizer(client, "importOrgM")
        code = host(client)
        client.cookies.clear()
        do_import(client, code, {"source": "topdeck", "payload": payload([ROUND_ONE])},
                  expect=401)

    def test_a_table_with_no_result_lands_awaiting_one(self, client):
        """An unfinished last round is the round the organizer is now running,
        so it arrives open with the undecided table still to rule."""
        organizer(client, "importOrgN")
        code = host(client)
        partial = {"round": 1, "tables": [table(1, 0, 1, winner=0), table(2, 2, 3)]}
        out = imported(client, code, [partial])
        assert out["rounds"][0]["awaiting"] == 1
        state = client.get(f"/api/tournament/{code}").json()
        assert state["round"]["status"] == "active"
        assert {p["status"] for p in state["pods"]} == {"complete", "awaiting_result"}

    def test_a_malformed_payload_writes_nothing_at_all(self, client):
        """Validation is a pass of its own before the first INSERT: a payload
        that fails halfway must not leave half an event behind."""
        organizer(client, "importOrgY")
        code = host(client)
        twice = {"round": 1, "tables": [
            table(1, 0, 1, winner=0),
            {"table": 2, "players": [person(2), person(2)]},
        ]}
        out = do_import(client, code,
                        {"source": "topdeck", "payload": payload([twice])}, expect=400)
        assert "twice" in out["detail"]
        assert client.get(f"/api/tournament/{code}/roster").json()["entrants"] == []
        assert q("SELECT COUNT(*) c FROM trounds WHERE tournament_code = ?",
                 (code,)).fetchone()["c"] == 0

    def test_an_earlier_round_may_not_be_left_unfinished(self, client):
        organizer(client, "importOrgO")
        code = host(client)
        partial = {"round": 1, "tables": [table(1, 0, 1)]}
        out = do_import(client, code,
                        {"source": "topdeck", "payload": payload([partial, ROUND_TWO])},
                        expect=409)
        assert "rule them here" in out["detail"]


class TestImportedCut:
    """'Top 8' has to land on the cut this app already runs, not a second one."""

    def test_the_bracket_round_is_flagged_as_elimination(self, client):
        organizer(client, "importOrgP")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        kinds = [r["kind"] for r in q(
            "SELECT kind FROM trounds WHERE tournament_code = ? ORDER BY number", (code,)
        ).fetchall()]
        assert kinds == ["swiss", "swiss", "elimination"]

    def test_the_round_number_on_the_wire_is_an_integer(self, client):
        organizer(client, "importOrgQ")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        rnd = client.get(f"/api/tournament/{code}").json()["round"]
        assert rnd["number"] == 3 and rnd["kind"] == "elimination"

    def test_the_cut_is_the_one_the_app_already_has(self, client):
        """Not a second notion of a cut: it shows up in the same `cut` view the
        organizer's own top cut produces, with seeds and who is still alive."""
        organizer(client, "importOrgR")
        code = host(client)
        out = imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        assert out["cutSeeded"] == 8
        cut = client.get(f"/api/tournament/{code}").json()["cut"]
        assert cut["cutTo"] == 8 and cut["rounds"] == 1
        assert sorted(s["seed"] for s in cut["seeds"]) == list(range(1, 9))
        assert sum(1 for s in cut["seeds"] if s["alive"]) == 4

    def test_the_bracket_continues_from_an_imported_cut(self, client):
        """The proof that the flag is the real one: the next round pairs from
        the bracket the import wrote, not from Swiss standings."""
        organizer(client, "importOrgS")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "elimination"
        assert r.json()["pods"] == 2 and r.json()["remaining"] == 4

    def test_a_cut_already_seeded_is_not_re_seeded(self, client):
        """cut_seed is written once. Re-running the import — the same payload,
        because that is all their export can give you — re-seeds nobody."""
        organizer(client, "importOrgT")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        before = {r["id"]: r["cut_seed"] for r in q(
            "SELECT id, cut_seed FROM entrants WHERE tournament_code = ?", (code,)).fetchall()}
        out = imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        assert out["cutSeeded"] == 0
        after = {r["id"]: r["cut_seed"] for r in q(
            "SELECT id, cut_seed FROM entrants WHERE tournament_code = ?", (code,)).fetchall()}
        assert after == before

    def test_a_bracket_round_imported_later_extends_the_same_cut(self, client):
        """The finals arrive in a later export. They are a fourth round, and
        the cut they belong to is the one already seeded — not a new one."""
        organizer(client, "importOrgW")
        code = host(client)
        imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT])
        finals = {"round": "Top 4", "tables": [table(1, 0, 3, winner=0), table(2, 1, 2, winner=1)]}
        out = imported(client, code, [ROUND_ONE, ROUND_TWO, TOP_EIGHT, finals])
        assert [(r["number"], r["skipped"]) for r in out["rounds"]][-1] == (4, False)
        assert out["cutSeeded"] == 0
        cut = client.get(f"/api/tournament/{code}").json()["cut"]
        assert cut["cutTo"] == 8 and cut["rounds"] == 2
        assert sum(1 for s in cut["seeds"] if s["alive"]) == 2


class TestResultKindsAreTyped:
    """The adapter exists so a foreign spelling never reaches the database.
    The endpoint refuses one anyway — an adapter is not the only caller."""

    def _pod(self, client, code):
        client.post(f"/api/tournament/{code}/rounds", json={})
        return client.get(f"/api/tournament/{code}").json()["pods"][0]

    def test_a_foreign_spelling_of_a_kind_is_refused(self, client):
        organizer(client, "importOrgU")
        code = host(client)
        client.post(f"/api/tournament/{code}/entrants", json={"names": ["u1", "u2"]})
        pod = self._pod(client, code)
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/result",
                        json={"kind": "Draw"})
        assert r.status_code == 400 and "kind must be one of" in r.json()["detail"]
        # and nothing was scored on the way to being refused
        assert all(s["points"] is None for s in
                   client.get(f"/api/tournament/{code}").json()["pods"][0]["seats"])

    def test_bye_is_an_accepted_kind(self, client):
        organizer(client, "importOrgV")
        code = host(client)
        client.post(f"/api/tournament/{code}/entrants", json={"names": ["v1", "v2"]})
        pod = self._pod(client, code)
        r = client.post(f"/api/tournament/{code}/pods/{pod['podId']}/result",
                        json={"kind": "bye"})
        assert r.status_code == 200, r.text
        assert client.get(f"/api/tournament/{code}/rounds/1").json()["pods"][0]["result"]["kind"] == "bye"
