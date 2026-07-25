"""Organizer rename of a roster entry, and CSV/JSON export of an event.

Both are organizer-only additions to an event that is otherwise read through
one polled snapshot. The rules worth pinning are the identity ones: a rename
moves a display name and nothing else, and nothing in an export ever carries
the integer primary key.
"""

import csv
import io

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


def organizer(client, username):
    client.cookies.clear()
    client.post(
        "/api/account/signup", json={"username": username, "password": "a good long password"}
    )
    client.post("/api/account/email", json={"email": f"{username}@example.com"})
    return client


def host(client, name="Export Night"):
    r = client.post("/api/tournament", json={"name": name, "mode": "life", "settings": {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    r = client.post(f"/api/tournament/{code}/entrants", json={"names": names})
    assert r.status_code == 200, r.text
    return r.json()["added"]


def played_event(client, names=None):
    """A tournament with one round played and reported, so results exist."""
    code = host(client)
    added = add(client, code, names or ["Ada", "Grace", "Alan", "Edsger"])
    r = client.post(f"/api/tournament/{code}/rounds", json={})
    assert r.status_code == 200, r.text
    state = client.get(f"/api/tournament/{code}").json()
    pod = state["pods"][0]
    places = [
        {"entrantId": s["entrantId"], "place": i}
        for i, s in enumerate(pod["seats"], 1)
    ]
    r = client.post(
        f"/api/tournament/{code}/pods/{pod['podId']}/result",
        json={"kind": "placement", "places": places, "note": 'called it, "cleanly"'},
    )
    assert r.status_code == 200, r.text
    return code, added, pod


class TestEntrantRename:
    def test_organizer_renames_a_roster_entry(self, client):
        organizer(client, "renameA")
        code = host(client)
        [ada] = add(client, code, ["Aad"])
        r = client.post(
            f"/api/tournament/{code}/entrants/{ada['entrantId']}/rename", json={"name": "Ada"}
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "entrantId": ada["entrantId"], "name": "Ada"}
        roster = client.get(f"/api/tournament/{code}/roster").json()
        assert [e["name"] for e in roster["entrants"]] == ["Ada"]

    def test_only_the_organizer_can_rename(self, client):
        organizer(client, "renameB")
        code = host(client)
        [e] = add(client, code, ["Ada"])
        organizer(client, "renameB_other")  # a different account
        assert (
            client.post(
                f"/api/tournament/{code}/entrants/{e['entrantId']}/rename", json={"name": "Mallory"}
            ).status_code
            == 403
        )
        client.cookies.clear()
        assert (
            client.post(
                f"/api/tournament/{code}/entrants/{e['entrantId']}/rename", json={"name": "Mallory"}
            ).status_code
            == 401
        )
        organizer(client, "renameB")
        roster = client.get(f"/api/tournament/{code}/roster").json()
        assert [x["name"] for x in roster["entrants"]] == ["Ada"]

    def test_rename_keeps_the_token_the_public_id_and_the_points(self, client):
        """The name is a label. Identity, credentials and history are not."""
        organizer(client, "renameC")
        code, added, pod = played_event(client)
        target = pod["seats"][0]
        token = client.post(
            f"/api/tournament/{code}/claim", json={"entrantId": target["entrantId"]}
        ).json()["entrantToken"]
        before = next(
            s for s in client.get(f"/api/tournament/{code}").json()["standings"]
            if s["entrantId"] == target["entrantId"]
        )

        r = client.post(
            f"/api/tournament/{code}/entrants/{target['entrantId']}/rename",
            json={"name": "Renamed Person"},
        )
        assert r.status_code == 200
        assert r.json()["entrantId"] == target["entrantId"]  # public id unchanged

        # the token still resolves to the same seat
        me = client.get(f"/api/tournament/{code}", params={"token": token}).json()["me"]
        assert me["entrantId"] == target["entrantId"]
        assert me["name"] == "Renamed Person"

        after = next(
            s for s in client.get(f"/api/tournament/{code}").json()["standings"]
            if s["entrantId"] == target["entrantId"]
        )
        assert after["points"] == before["points"]
        assert after["wins"] == before["wins"]
        assert after["podsPlayed"] == before["podsPlayed"]
        assert after["name"] == "Renamed Person"

    def test_rename_does_not_relabel_a_seated_room(self, client):
        """A room seat is a separate identity — the pod in progress keeps its
        player rows, and the roster shows the new name from the next round."""
        organizer(client, "renameD")
        code, _, pod = played_event(client)
        target = pod["seats"][0]
        room = client.get(f"/api/tournament/{code}").json()["pods"][0]["roomCode"]
        client.post(
            f"/api/tournament/{code}/entrants/{target['entrantId']}/rename",
            json={"name": "Later Name"},
        )
        names = [
            r["name"] for r in q("SELECT name FROM players WHERE room_code = ?", (room,)).fetchall()
        ]
        assert target["name"] in names
        assert "Later Name" not in names

    def test_duplicate_names_are_allowed(self, client):
        """Two people really can be named Ada — a name is not identity."""
        organizer(client, "renameE")
        code = host(client)
        first, second = add(client, code, ["Ada", "Grace"])
        r = client.post(
            f"/api/tournament/{code}/entrants/{second['entrantId']}/rename", json={"name": "Ada"}
        )
        assert r.status_code == 200
        roster = client.get(f"/api/tournament/{code}/roster").json()["entrants"]
        assert [e["name"] for e in roster] == ["Ada", "Ada"]
        assert len({e["entrantId"] for e in roster}) == 2

    def test_a_blank_or_oversized_name_is_refused(self, client):
        organizer(client, "renameF")
        code = host(client)
        [e] = add(client, code, ["Ada"])
        url = f"/api/tournament/{code}/entrants/{e['entrantId']}/rename"
        assert client.post(url, json={"name": ""}).status_code == 422
        assert client.post(url, json={"name": "   "}).status_code == 400
        assert client.post(url, json={"name": "x" * 81}).status_code == 422
        assert client.get(f"/api/tournament/{code}/roster").json()["entrants"][0]["name"] == "Ada"

    def test_an_unknown_or_internal_id_is_a_404(self, client):
        """Posting the integer primary key where a public id belongs must not
        find the row — the same rule the claim path holds to."""
        organizer(client, "renameG")
        code = host(client)
        [e] = add(client, code, ["Ada"])
        internal = q(
            "SELECT id FROM entrants WHERE public_id = ?", (e["entrantId"],)
        ).fetchone()["id"]
        assert (
            client.post(
                f"/api/tournament/{code}/entrants/{internal}/rename", json={"name": "Mallory"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/tournament/{code}/entrants/nobody/rename", json={"name": "Mallory"}
            ).status_code
            == 404
        )


def parsed_csv(text):
    return list(csv.reader(io.StringIO(text)))


class TestExport:
    def test_standings_csv_has_a_header_and_a_row_per_entrant(self, client):
        organizer(client, "exportA")
        code, added, _ = played_event(client)
        r = client.get(f"/api/tournament/{code}/export", params={"what": "standings", "format": "csv"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        assert f'filename="{code}-standings.csv"' in r.headers["content-disposition"]
        rows = parsed_csv(r.text)
        assert rows[0][:3] == ["rank", "entrantId", "name"]
        assert len(rows) == 1 + len(added)
        assert [row[0] for row in rows[1:]] == ["1", "2", "3", "4"]

    def test_csv_escapes_commas_quotes_and_newlines_in_names(self, client):
        """Entrant names are free text. Joining on commas by hand loses rows."""
        organizer(client, "exportB")
        code = host(client)
        nasty = ['Ada, the "Countess"', "line\nbreak", "plain"]
        add(client, code, nasty)
        r = client.get(f"/api/tournament/{code}/export", params={"format": "csv"})
        rows = parsed_csv(r.text)
        assert len(rows) == 4
        name_col = rows[0].index("name")
        assert sorted(row[name_col] for row in rows[1:]) == sorted(nasty)

    def test_csv_neutralizes_spreadsheet_formulas(self, client):
        """A name is typed by a human at a shop counter; it must never execute
        when the organizer opens the file."""
        organizer(client, "exportC")
        code = host(client)
        add(client, code, ["=HYPERLINK(\"http://evil\",\"click\")"])
        r = client.get(f"/api/tournament/{code}/export", params={"format": "csv"})
        rows = parsed_csv(r.text)
        name_col = rows[0].index("name")
        assert rows[1][name_col].startswith("'=")
        # the roster itself is untouched — the guard is a rendering concern
        assert client.get(f"/api/tournament/{code}/roster").json()["entrants"][0][
            "name"
        ].startswith("=")

    def test_results_csv_carries_every_seat_of_every_pod(self, client):
        organizer(client, "exportD")
        code, added, pod = played_event(client)
        r = client.get(f"/api/tournament/{code}/export", params={"what": "results", "format": "csv"})
        assert r.status_code == 200
        rows = parsed_csv(r.text)
        header = rows[0]
        assert header[:5] == ["round", "table", "seat", "entrantId", "name"]
        assert len(rows) == 1 + len(pod["seats"])
        body = [dict(zip(header, row)) for row in rows[1:]]
        assert {b["round"] for b in body} == {"1"}
        assert sorted(b["place"] for b in body) == ["1", "2", "3", "4"]
        assert {b["kind"] for b in body} == {"placement"}
        assert {b["source"] for b in body} == {"organizer"}
        assert {b["note"] for b in body} == {'called it, "cleanly"'}

    def test_json_export_carries_both_tables(self, client):
        organizer(client, "exportE")
        code, added, pod = played_event(client)
        r = client.get(f"/api/tournament/{code}/export", params={"what": "all"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/json")
        assert f'filename="{code}-all.json"' in r.headers["content-disposition"]
        payload = r.json()
        assert payload["tournament"]["code"] == code
        assert len(payload["standings"]) == len(added)
        assert len(payload["results"]) == len(pod["seats"])
        assert payload["standings"][0]["rank"] == 1

    def test_export_only_ever_carries_public_ids(self, client):
        """The integer primary key never leaves the server, in any format."""
        organizer(client, "exportF")
        code, added, _ = played_event(client)
        publics = {e["entrantId"] for e in added}
        internals = {
            str(r["id"]) for r in q(
                "SELECT id FROM entrants WHERE tournament_code = ?", (code,)
            ).fetchall()
        }
        payload = client.get(f"/api/tournament/{code}/export", params={"what": "all"}).json()
        for row in payload["standings"] + payload["results"]:
            assert row["entrantId"] in publics
            assert "publicId" not in row
        assert not any("entrantId" in row and str(row["entrantId"]) in internals
                       for row in payload["standings"])

        for what in ("standings", "results"):
            rows = parsed_csv(
                client.get(
                    f"/api/tournament/{code}/export", params={"what": what, "format": "csv"}
                ).text
            )
            col = rows[0].index("entrantId")
            assert {row[col] for row in rows[1:]} <= publics

    def test_export_is_organizer_only(self, client):
        organizer(client, "exportG")
        code, _, _ = played_event(client)
        organizer(client, "exportG_other")
        assert client.get(f"/api/tournament/{code}/export").status_code == 403
        client.cookies.clear()
        assert client.get(f"/api/tournament/{code}/export").status_code == 401

    def test_unknown_format_or_table_is_a_400(self, client):
        organizer(client, "exportH")
        code = host(client)
        assert client.get(
            f"/api/tournament/{code}/export", params={"format": "pdf"}
        ).status_code == 400
        assert client.get(
            f"/api/tournament/{code}/export", params={"what": "everything"}
        ).status_code == 400
        # a CSV file is one table, so "all" has no meaning there
        assert client.get(
            f"/api/tournament/{code}/export", params={"what": "all", "format": "csv"}
        ).status_code == 400

    def test_export_of_an_event_with_no_rounds_is_still_a_file(self, client):
        """Header row only. An organizer exporting too early gets an empty
        table, not a 404 to puzzle over."""
        organizer(client, "exportI")
        code = host(client)
        add(client, code, ["Ada"])
        rows = parsed_csv(
            client.get(
                f"/api/tournament/{code}/export", params={"what": "results", "format": "csv"}
            ).text
        )
        assert len(rows) == 1
        assert rows[0][0] == "round"

    def test_a_renamed_entrant_exports_under_the_new_name(self, client):
        """The two features meet here: rename changes the label the export
        carries, and nothing else about the row."""
        organizer(client, "exportJ")
        code, _, pod = played_event(client)
        target = pod["seats"][0]
        client.post(
            f"/api/tournament/{code}/entrants/{target['entrantId']}/rename",
            json={"name": "Ada Lovelace"},
        )
        payload = client.get(f"/api/tournament/{code}/export", params={"what": "all"}).json()
        row = next(r for r in payload["results"] if r["entrantId"] == target["entrantId"])
        assert row["name"] == "Ada Lovelace"
        assert row["place"] == 1
