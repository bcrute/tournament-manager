"""The sanctioning id: generic collection, worded by the game profile.

The setting used to be `collectWizardsEmail` and the 422 used to name Wizards,
which is wrong for every game that isn't Magic — including the case that has no
sanctioning body at all, where the old code would happily demand an id nobody
could hold. These pin the generic behaviour and the deprecated spellings that
shipped clients still send.
"""

import json
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import games
from app.accounts import router as accounts_router
from app.db import q
from app.tournaments import router as tournaments_router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def unsanctioned_game():
    """A profile with no sanctioning account — the case MTG cannot exercise.

    Registered for the length of one test only: `GET /games` is pinned to the
    real registry elsewhere, and this profile is a fixture, not a product.
    """
    p = replace(
        games.MTG,
        key="unsanctioned",
        name="Unsanctioned Game",
        publisher="Nobody",
        sanctioning_account=None,
        structures=(),
        notes={},
    )
    games._PROFILES[p.key] = p
    try:
        yield p
    finally:
        del games._PROFILES[p.key]


def organizer(client, username):
    client.cookies.clear()
    client.post("/api/account/signup",
                json={"username": username, "password": "a good long password"})
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, settings=None, game="mtg", expect=200):
    r = client.post("/api/tournament",
                    json={"name": "Sanctioned Night", "game": game, "settings": settings or {}})
    assert r.status_code == expect, r.text
    return r.json()["code"] if r.status_code == 200 else r


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def stored_id(entrant_id):
    return q("SELECT wizards_email FROM entrants WHERE public_id = ?",
             (entrant_id,)).fetchone()["wizards_email"]


class TestSanctioningIdCollection:
    def test_required_blocks_a_claim_and_names_the_id_from_the_profile(self, client):
        organizer(client, "sanc1")
        code = host(client, {"collectSanctioningId": "required"})
        added = add(client, code, ["s1", "s2", "s3", "s4"])
        client.cookies.clear()
        r = client.post(f"/api/tournament/{code}/claim",
                        json={"entrantId": added[0]["entrantId"]})
        assert r.status_code == 422
        # the wording is the profile's, not this module's
        assert games.MTG.sanctioning_account in r.json()["detail"]
        ok = client.post(f"/api/tournament/{code}/claim",
                         json={"entrantId": added[0]["entrantId"],
                               "sanctioningId": "ada@example.com"})
        assert ok.status_code == 200
        assert stored_id(added[0]["entrantId"]) == "ada@example.com"

    def test_optional_stores_what_is_given_and_off_discards_it(self, client):
        organizer(client, "sanc2")
        opt = host(client, {"collectSanctioningId": "optional"})
        off = host(client, {"collectSanctioningId": "off"})
        a = add(client, opt, ["s5", "s6", "s7", "s8"])
        b = add(client, off, ["s9", "s10", "s11", "s12"])
        client.cookies.clear()
        for code, added in ((opt, a), (off, b)):
            client.post(f"/api/tournament/{code}/claim",
                        json={"entrantId": added[0]["entrantId"],
                              "sanctioningId": "grace@example.com"})
        assert stored_id(a[0]["entrantId"]) == "grace@example.com"
        assert stored_id(b[0]["entrantId"]) is None

    def test_a_bad_mode_is_rejected_rather_than_silently_meaning_optional(self, client):
        organizer(client, "sanc3")
        r = host(client, {"collectSanctioningId": "yes"}, expect=400)
        assert "collectSanctioningId" in r.json()["detail"]

    def test_the_id_is_never_exposed_on_the_public_roster_or_state(self, client):
        organizer(client, "sanc4")
        code = host(client, {"collectSanctioningId": "optional"})
        added = add(client, code, ["s13", "s14", "s15", "s16"])
        client.cookies.clear()
        client.post(f"/api/tournament/{code}/claim",
                    json={"entrantId": added[0]["entrantId"], "sanctioningId": "priv@example.com"})
        assert "priv@example.com" not in json.dumps(
            client.get(f"/api/tournament/{code}/roster").json())
        assert "priv@example.com" not in json.dumps(
            client.get(f"/api/tournament/{code}").json())


class TestDeprecatedSpellings:
    """A build already in someone's pocket keeps working."""

    def test_the_old_setting_key_is_rewritten_to_the_new_one(self, client):
        organizer(client, "sanc5")
        code = host(client, {"collectWizardsEmail": "required"})
        cfg = client.get(f"/api/tournament/{code}").json()["tournament"]["settings"]
        assert cfg["collectSanctioningId"] == "required"
        assert "collectWizardsEmail" not in cfg   # one name in the database, not two

    def test_the_old_setting_key_is_still_validated_against_the_profile(
        self, client, unsanctioned_game
    ):
        organizer(client, "sanc6")
        r = host(client, {"collectWizardsEmail": "required"},
                 game=unsanctioned_game.key, expect=400)
        assert "sanctioning account" in r.json()["detail"]

    def test_the_new_key_wins_when_both_are_sent(self, client):
        organizer(client, "sanc7")
        code = host(client, {"collectWizardsEmail": "required", "collectSanctioningId": "off"})
        cfg = client.get(f"/api/tournament/{code}").json()["tournament"]["settings"]
        assert cfg["collectSanctioningId"] == "off"

    def test_the_old_claim_field_still_satisfies_a_required_id(self, client):
        organizer(client, "sanc8")
        code = host(client, {"collectSanctioningId": "required"})
        added = add(client, code, ["s17", "s18", "s19", "s20"])
        client.cookies.clear()
        r = client.post(f"/api/tournament/{code}/claim",
                        json={"entrantId": added[0]["entrantId"], "wizardsEmail": "old@example.com"})
        assert r.status_code == 200
        assert stored_id(added[0]["entrantId"]) == "old@example.com"


class TestGamesWithoutASanctioningBody:
    def test_collection_cannot_be_turned_on_at_all(self, client, unsanctioned_game):
        organizer(client, "sanc9")
        for mode in ("required", "optional"):
            r = host(client, {"collectSanctioningId": mode},
                     game=unsanctioned_game.key, expect=400)
            assert unsanctioned_game.name in r.json()["detail"]
        # "off" is the only honest answer, and it is accepted
        assert host(client, {"collectSanctioningId": "off"}, game=unsanctioned_game.key)

    def test_a_legacy_row_demanding_an_id_does_not_strand_the_player(
        self, client, unsanctioned_game
    ):
        """Settings written before that check existed must not block a claim on
        an id the server has no word for."""
        organizer(client, "sanc10")
        code = host(client, game=unsanctioned_game.key)
        q("UPDATE tournaments SET settings = ? WHERE code = ?",
          (json.dumps({"collectSanctioningId": "required"}), code))
        added = add(client, code, ["s21", "s22", "s23", "s24"])
        client.cookies.clear()
        r = client.post(f"/api/tournament/{code}/claim", json={"entrantId": added[0]["entrantId"]})
        assert r.status_code == 200
        assert stored_id(added[0]["entrantId"]) is None   # and nothing is stored either


class TestRosterAdvertisesTheLabel:
    """The claim form is drawn before the player holds any credential, so the
    roster is the only place it can learn what to ask for."""

    def test_the_roster_carries_the_profile_label_when_collection_is_on(self, client):
        organizer(client, "sanc11")
        code = host(client, {"collectSanctioningId": "required"})
        s = client.get(f"/api/tournament/{code}/roster").json()["sanctioning"]
        assert s == {"collect": "required", "label": games.MTG.sanctioning_account}

    def test_no_label_is_offered_when_collection_is_off(self, client):
        organizer(client, "sanc12")
        code = host(client)
        assert client.get(f"/api/tournament/{code}/roster").json()["sanctioning"] == {
            "collect": "off", "label": None
        }

    def test_a_game_with_no_sanctioning_body_never_advertises_collection(
        self, client, unsanctioned_game
    ):
        organizer(client, "sanc13")
        code = host(client, game=unsanctioned_game.key)
        q("UPDATE tournaments SET settings = ? WHERE code = ?",
          (json.dumps({"collectSanctioningId": "required"}), code))
        assert client.get(f"/api/tournament/{code}/roster").json()["sanctioning"] == {
            "collect": "off", "label": None
        }
