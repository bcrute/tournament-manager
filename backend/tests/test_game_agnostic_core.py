"""The core is game-agnostic — driven, not asserted.

§8 of the contract makes two claims that can only be checked by *using* the
server: "the core contains no MTG knowledge; MTG is a profile over the core",
and "adding a game should require no edits to `tournaments.py`; if it does, that
is a bug". Prose cannot hold either one down, so this module runs a whole event
— create, entrants, round, result, standings, close, a second round, a cut, a
bracket — on a profile that is nothing like Magic: three to a table, a resource
that counts *up*, no room modes, no sanctioning body, no published structures.

The profile is synthetic on purpose. Registering a real published game means
sourcing its official structures, which is a separate decision with its own
evidence rule (`official=True` requires a document); this behaviour has to be
provable without one. The only thing this test adds anywhere is one entry in the
games registry — if any of it needed a line changed in `tournaments.py`, the
claim would be false.
"""

import ast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import games, tournaments
from app.accounts import router as accounts_router
from app.db import q
from app.games import GameProfile
from app.table import router as table_router
from app.tournaments import router as tournaments_router


#: Deliberately unlike MTG in every field the core could have assumed:
#: pods of three rather than four, a resource that starts at zero and counts up
#: to a goal, no room modes, no sanctioning account, no extra turns, no
#: structures. Nothing here is a real game — it is a fixture, and it is
#: registered only for the life of this module.
SYNTHETIC = GameProfile(
    key="synthetic",
    name="Synthetic Test Game",
    publisher="Nobody — this is a test fixture",
    default_pod_size=3,
    default_round_minutes=25,
    resource="corruption",
    resource_start=0,
    resource_direction="up",
    resource_goal=12,
    modes=(),
    time_called_policies=("draw_all", "organizer_decides"),
    elimination_time_policy=None,
    sanctioning_account=None,
    extra_turns_at_time=0,
    structures=(),
)


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    games._PROFILES[SYNTHETIC.key] = SYNTHETIC
    try:
        with TestClient(app, base_url="https://testserver") as c:
            yield c
    finally:
        games._PROFILES.pop(SYNTHETIC.key, None)


def organizer(client, username):
    client.cookies.clear()
    client.post(
        "/api/account/signup", json={"username": username, "password": "a good long password"}
    )
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, name="Synthetic night", **body):
    r = client.post("/api/tournament", json={"name": name, "game": SYNTHETIC.key, **body})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    r = client.post(f"/api/tournament/{code}/entrants", json={"names": names})
    assert r.status_code == 200, r.text
    return r.json()["added"]


def state(client, code):
    return client.get(f"/api/tournament/{code}").json()


def report(client, code, pod, order):
    r = client.post(
        f"/api/tournament/{code}/pods/{pod['podId']}/result",
        json={
            "kind": "placement",
            "places": [{"entrantId": e, "place": i} for i, e in enumerate(order, 1)],
        },
    )
    assert r.status_code == 200, r.text


def play_round(client, code, first=None):
    """Report every open pod — `first` names the entrant to place first where
    they are seated — then close the round."""
    for pod in state(client, code)["pods"]:
        if pod["status"] == "complete":
            continue  # a bye is already decided
        seats = [s["entrantId"] for s in pod["seats"]]
        winner = first if first in seats else seats[0]
        report(client, code, pod, [winner] + [s for s in seats if s != winner])
    r = client.post(f"/api/tournament/{code}/rounds/close")
    assert r.status_code == 200, r.text


class TestNothingMTGReachesANewGame:
    """Every per-game fact comes from the profile, so none of MTG's arrive."""

    def test_the_registry_is_the_only_place_the_game_was_added(self, client):
        listed = {g["key"]: g for g in client.get("/api/tournament/games").json()["games"]}
        assert SYNTHETIC.key in listed, "registering a profile is all it should take"
        g = listed[SYNTHETIC.key]
        assert g["defaultPodSize"] == 3
        assert (g["resource"], g["resourceStart"], g["resourceDirection"], g["resourceGoal"]) == (
            "corruption",
            0,
            "up",
            12,
        )
        assert g["modes"] == [] and g["sanctioningAccount"] is None
        assert g["structures"] == []

    def test_defaults_are_the_profiles_and_carry_no_mtg_numbers(self):
        cfg = tournaments.defaults_for(SYNTHETIC.key)
        assert cfg["podSize"] == 3
        assert cfg["roundMinutes"] == 25
        assert cfg["extraTurns"] == 0
        assert cfg["timeCalledPolicy"] == "draw_all"
        # `startingLife` keeps its wire name (§8) but is the profile's resource
        # start — zero here, and never MTG's forty
        assert cfg["startingLife"] == 0
        mtg = tournaments.defaults_for(games.MTG.key)
        assert cfg["podSize"] != mtg["podSize"]
        assert cfg["startingLife"] != mtg["startingLife"]
        assert cfg["extraTurns"] != mtg["extraTurns"]
        # everything else is the generic table, identical between the two games
        generic = set(tournaments.GENERIC_SETTINGS)
        assert {k: cfg[k] for k in generic} == {k: mtg[k] for k in generic}

    def test_a_created_event_serves_the_profiles_settings(self, client):
        organizer(client, "agnosticA")
        code = host(client)
        t = state(client, code)["tournament"]
        assert t["game"] == SYNTHETIC.key
        assert t["mode"] == ""  # no room modes: nothing to name
        assert t["settings"]["podSize"] == 3
        assert t["settings"]["roundMinutes"] == 25

    def test_another_games_mode_is_not_quietly_accepted(self, client):
        organizer(client, "agnosticB")
        r = client.post(
            "/api/tournament",
            json={"name": "x", "game": SYNTHETIC.key, "mode": games.MTG.modes[0]},
        )
        assert r.status_code == 400, r.text

    def test_a_policy_this_game_does_not_offer_is_refused(self, client):
        organizer(client, "agnosticC")
        r = client.post(
            "/api/tournament",
            json={
                "name": "x",
                "game": SYNTHETIC.key,
                "settings": {"timeCalledPolicy": "highest_resource"},
            },
        )
        assert r.status_code == 400, r.text

    def test_a_game_with_no_sanctioning_body_cannot_collect_an_id(self, client):
        organizer(client, "agnosticD")
        r = client.post(
            "/api/tournament",
            json={
                "name": "x",
                "game": SYNTHETIC.key,
                "settings": {"collectSanctioningId": "required"},
            },
        )
        assert r.status_code == 400, r.text
        code = host(client)
        roster = client.get(f"/api/tournament/{code}/roster").json()
        assert roster["sanctioning"] == {"collect": "off", "label": None}

    def test_a_game_with_no_structures_is_told_so_rather_than_advised(self, client):
        organizer(client, "agnosticE")
        code = host(client)
        add(client, code, [f"e{i}" for i in range(6)])
        r = client.get(f"/api/tournament/{code}/plan")
        assert r.status_code == 409, r.text


class TestAWholeEventOnASyntheticProfile:
    """create → entrants → round → result → standings, on nothing but a profile."""

    def test_an_event_runs_end_to_end(self, client):
        organizer(client, "agnosticF")
        code = host(client, name="Corruption league")
        entrants = add(client, code, [f"p{i}" for i in range(6)])
        assert len(entrants) == 6

        # a player claims their seat with no id to hand over
        claim = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": entrants[0]["entrantId"]}
        )
        assert claim.status_code == 200, claim.text
        token = claim.json()["entrantToken"]

        rooms_before = q("SELECT COUNT(*) c FROM rooms").fetchone()["c"]
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 200, r.text
        assert r.json()["pods"] == 2, "six entrants, three to a table"

        snapshot = state(client, code)
        assert [len(p["seats"]) for p in snapshot["pods"]] == [3, 3]
        assert all(p["roomCode"] is None for p in snapshot["pods"])
        assert q("SELECT COUNT(*) c FROM rooms").fetchone()["c"] == rooms_before

        # the claimed entrant is told where they are sitting, with no room
        mine = client.get(f"/api/tournament/{code}?token={token}").json()["myPod"]
        assert mine is not None and mine["roomCode"] is None

        winner = entrants[0]["entrantId"]
        play_round(client, code, first=winner)

        standings = state(client, code)["standings"]
        assert len(standings) == 6
        top = next(s for s in standings if s["entrantId"] == winner)
        assert top["points"] == 3, "generic win points, not a game's own scoring"
        assert standings[0]["points"] >= standings[-1]["points"]

        # a second round pairs from those standings without anything game-shaped
        assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200
        assert [len(p["seats"]) for p in state(client, code)["pods"]] == [3, 3]
        play_round(client, code, first=winner)
        assert state(client, code)["standings"][0]["points"] == 6

    def test_time_called_settles_a_roomless_pod_on_this_games_policy(self, client):
        """No rooms means no resource to rank and no turns to count, so the
        profile's first policy — a draw — decides immediately."""
        organizer(client, "agnosticG")
        code = host(client)
        add(client, code, [f"t{i}" for i in range(6)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        r = client.post(f"/api/tournament/{code}/rounds/time")
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "decided": 2, "extraTurns": 0, "turns": 0,
                            "policy": "draw_all"}
        assert all(p["status"] == "complete" for p in state(client, code)["pods"])
        assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200
        # a draw is worth the generic draw points to everyone
        assert {s["points"] for s in state(client, code)["standings"]} == {1}

    def test_a_cut_and_a_bracket_run_without_a_published_structure(self, client):
        """A game with no structures names its own cut size; everything after
        that is the generic bracket."""
        organizer(client, "agnosticH")
        code = host(client)
        entrants = add(client, code, [f"c{i}" for i in range(6)])
        client.post(f"/api/tournament/{code}/rounds", json={})
        play_round(client, code, first=entrants[0]["entrantId"])

        assert client.post(f"/api/tournament/{code}/cut", json={}).status_code == 409
        r = client.post(f"/api/tournament/{code}/cut", json={"size": 4})
        assert r.status_code == 200, r.text
        assert r.json()["cutTo"] == 4

        bracket = state(client, code)
        assert bracket["round"]["kind"] == "elimination"
        # four into pods of three: one bye off the top, then a table of three
        assert sorted(len(p["seats"]) for p in bracket["pods"]) == [1, 3]
        play_round(client, code)
        assert state(client, code)["round"]["status"] == "closed"


class TestWhatArrivingMidGameMeansIsTheRoomsToSay:
    """The one branch on a mode that was left in `tournaments.py`.

    Seating an entrant into a game already under way had the tournament layer
    check for Treachery by name, to warn that nobody had dealt the arrival an
    identity card. The warning is right and still happens — it just belongs to
    the room, which is where a mode means anything. These tests drive it through
    the organizer's move, so the behaviour is pinned at the boundary that
    matters rather than at the helper.
    """

    def events_in(self, room_code):
        return [
            r["text"]
            for r in q(
                "SELECT text FROM events WHERE room_code = ? ORDER BY id", (room_code,)
            ).fetchall()
        ]

    def move_into_a_live_table(self, client, username, mode):
        """An event on the game that does have room modes, with one table's game
        already under way, and somebody moved into it.

        The *room* is put in `mode`, not the tournament: Treachery is a room mode
        and no longer a tournament format — it has no standings Swiss can rank —
        so an event is always seated in the game's default. Which is the claim
        this class is making, in the setup as well as the assertion: the mode is
        the room's, and the tournament layer neither sets it nor reads it.
        """
        organizer(client, username)
        r = client.post("/api/tournament", json={"name": "Move night"})
        assert r.status_code == 200, r.text
        code = r.json()["code"]
        client.post(
            f"/api/tournament/{code}/entrants",
            json={"names": [f"{username}-{i}" for i in range(8)]},
        )
        assert client.post(f"/api/tournament/{code}/rounds", json={}).status_code == 200

        dest, src = state(client, code)["pods"][:2]
        q(
            "UPDATE rooms SET status = 'playing', mode = ? WHERE code = ?",
            (mode, dest["roomCode"]),
        )
        who = src["seats"][0]["entrantId"]
        r = client.post(
            f"/api/tournament/{code}/pods/{dest['podId']}/move", json={"entrantId": who}
        )
        assert r.status_code == 200, r.text
        return self.events_in(dest["roomCode"])

    def test_a_treachery_table_is_told_the_arrival_has_no_identity(self, client):
        log = self.move_into_a_live_table(client, "arriveA", "treachery")
        assert any("has no identity card" in line for line in log)

    def test_a_plain_life_table_is_told_only_that_they_arrived(self, client):
        log = self.move_into_a_live_table(client, "arriveB", "life")
        assert any("was moved to this table" in line for line in log)
        assert not any("identity card" in line for line in log)


class TestTournamentsPyNamesNoGame:
    """The other half of the claim, checked against the file itself.

    A game-agnostic core cannot be proved by running one event: code can pass a
    test and still carry a branch on a game's name that the next game trips
    over. These look at `tournaments.py` directly for the shapes that would make
    adding a game an edit here — a literal naming a game, its modes or its
    resource, and a profile constant imported to be branched on.
    """

    @staticmethod
    def _code_literals() -> dict:
        """Every string constant in `tournaments.py` bar docstrings, by line.

        Comments and docstrings cite the MTR freely and should: explaining *why*
        a rule is what it is names the game it came from. What matters is what
        the code compares and stores.
        """
        source = open(tournaments.__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node) is not None:
                    docstrings.add(id(node.body[0].value))
        found: dict = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                found.setdefault(node.value, []).append(node.lineno)
        return found

    def test_no_literal_names_a_game_its_modes_or_its_resource(self):
        vocabulary = {}
        for profile in list(games._PROFILES.values()):
            for word in (profile.key, profile.resource, *profile.modes):
                vocabulary[word] = profile.key
        literals = self._code_literals()
        offenders = {
            word: literals[word] for word in vocabulary if word in literals
        }
        assert not offenders, (
            "tournaments.py names a specific game's vocabulary: "
            f"{offenders} — that fact belongs in the profile (§8)"
        )

    def test_no_game_profile_is_imported_to_be_branched_on(self):
        held = [
            name for name, value in vars(tournaments).items() if isinstance(value, GameProfile)
        ]
        assert not held, f"tournaments.py holds profile constants {held}; use profile_for()"

    def test_the_default_game_comes_from_the_registry(self):
        """The one game name this module used to spell was its default. It is
        now the registry's, so a server that leads with another game needs no
        edit here."""
        body = tournaments.CreateBody(name="x")
        assert body.game == games.DEFAULT_GAME
