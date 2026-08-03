"""An exported identifier has to come back in unchanged.

The CSV export escapes cells a spreadsheet would read as a formula by gluing a
`'` to the front. That is right for free text — an entrant called
`=HYPERLINK(...)` would otherwise run on the organizer's machine — and wrong
for `entrantId`, which was in the same set. `token_urlsafe` uses the base64url
alphabet, so about one id in sixty-four began with `-`, and those exports
carried an id that matched nothing on the other side.

It reached production and survived three green local runs and several CI runs
because it needed a particular random id to appear. These tests do not roll
dice: they write the awkward id into the database and then look.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import router as accounts_router
from app.db import q
from app.table import router as table_router
from app.tournaments import csv_text, new_public_id, router as tournaments_router
from conftest import verified_email


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(table_router, prefix="/api/table")
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def event(client):
    """An organizer with one entrant, whose public id we then control."""
    client.cookies.clear()
    username = f"csv{new_public_id()}"
    client.post(
        "/api/account/signup",
        json={"username": username, "password": "correct horse battery"},
    )
    verified_email(username, "csv@example.com")
    code = client.post("/api/tournament", json={"name": "CSV Night"}).json()["code"]
    client.post(f"/api/tournament/{code}/entrants", json={"names": ["Ada Lovelace"]})
    return code


def csv_rows(client, code, what):
    text = client.get(
        f"/api/tournament/{code}/export", params={"what": what, "format": "csv"}
    ).text
    return [line.split(",") for line in text.strip().splitlines()]


def set_public_id(code, value):
    row = q("SELECT id FROM entrants WHERE tournament_code = ?", (code,)).fetchone()
    q("UPDATE entrants SET public_id = ? WHERE id = ?", (value, row["id"]))
    return value


class TestIdentifiersSurviveTheExport:
    def test_an_id_starting_with_a_hyphen_is_not_rewritten(self, client, event):
        """The exact shipped bug. `-EkWzf1DKKA` came out as `'-EkWzf1DKKA`."""
        pid = set_public_id(event, "-EkWzf1DKKA")
        rows = csv_rows(client, event, "standings")
        col = rows[0].index("entrantId")
        assert [r[col] for r in rows[1:]] == [pid]

    def test_the_json_export_agrees_with_the_csv(self, client, event):
        pid = set_public_id(event, "-JsonAgree1")
        payload = client.get(
            f"/api/tournament/{event}/export", params={"what": "all"}
        ).json()
        assert {r["entrantId"] for r in payload["standings"]} == {pid}

    def test_an_ordinary_id_is_untouched_as_well(self, client, event):
        pid = set_public_id(event, "SP8XxFc2D2Y")
        rows = csv_rows(client, event, "standings")
        col = rows[0].index("entrantId")
        assert [r[col] for r in rows[1:]] == [pid]

    def test_the_id_matches_what_the_roster_serves(self, client, event):
        """Round-trip is the whole point: the id in the file is the id an
        importer or a human would look up."""
        pid = set_public_id(event, "-RoundTrip1")
        roster = client.get(f"/api/tournament/{event}/roster").json()
        served = {e["entrantId"] for e in roster["entrants"]}
        rows = csv_rows(client, event, "standings")
        col = rows[0].index("entrantId")
        assert {r[col] for r in rows[1:]} <= served
        assert pid in served


class TestFreeTextIsStillEscaped:
    """The guard has to stay where it was actually earning its keep."""

    def test_a_name_that_looks_like_a_formula_is_defused(self, client):
        assert csv_text("=HYPERLINK(\"http://evil\",\"click\")").startswith("'=")

    def test_every_formula_lead_character(self):
        for lead in ("=", "+", "-", "@", "\t", "\r"):
            assert csv_text(f"{lead}danger") == f"'{lead}danger"

    def test_ordinary_text_is_left_alone(self):
        assert csv_text("Ada Lovelace") == "Ada Lovelace"
        assert csv_text("") == ""
        assert csv_text(None) == ""

    def test_an_entrant_named_like_a_formula_is_escaped_in_the_file(self, client, event):
        q(
            "UPDATE entrants SET name = ? WHERE tournament_code = ?",
            ("=cmd|' /c calc'!A1", event),
        )
        text = client.get(
            f"/api/tournament/{event}/export", params={"what": "standings", "format": "csv"}
        ).text
        assert "'=cmd" in text
        assert ",=cmd" not in text


class TestGeneratedIdsAvoidTheProblem:
    def test_no_generated_id_starts_with_a_hyphen(self):
        """Belt as well as braces: the escaping no longer touches ids, and ids
        no longer look like formulas to a spreadsheet either. Enough draws that
        a one-in-sixty-four character would show up many times over."""
        assert not any(new_public_id().startswith("-") for _ in range(4000))

    def test_they_are_still_the_right_shape(self):
        ids = {new_public_id() for _ in range(500)}
        assert len(ids) == 500          # still random, still unique
        assert all(len(i) >= 10 for i in ids)
