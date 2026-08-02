"""Tournament idle expiry, and the pod-room exemption that has to end with it.

A room idles out after 3h; a tournament gets a whole day, because a field
breaking for lunch is not an abandoned event. The pair only works if both
clocks agree: a pod room is exempt from the room sweep exactly while its
tournament is live, so expiring an event must hand its rooms back to the sweep
rather than strand them open behind a tournament nobody is running.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.table as tbl
import app.tournaments as trn
from app.accounts import router as accounts_router
from app.db import q
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
    client.post("/api/account/signup", json={"username": username, "password": "a good long password"})
    verified_email(username)
    return client


def host(client, name="Friday Night"):
    r = client.post("/api/tournament", json={"name": name, "mode": "life", "settings": {}})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def add(client, code, names):
    return client.post(f"/api/tournament/{code}/entrants", json={"names": names}).json()["added"]


def open_round(client, code):
    r = client.post(f"/api/tournament/{code}/rounds", json={})
    assert r.status_code == 200, r.text
    return r.json()


def finish_round(client, code):
    """Report every pod, close the round — the only way to reach `end`."""
    for pod in client.get(f"/api/tournament/{code}").json()["pods"]:
        client.post(
            f"/api/tournament/{code}/pods/{pod['podId']}/result",
            json={"kind": "placement",
                  "places": [{"entrantId": s["entrantId"], "place": i}
                             for i, s in enumerate(pod["seats"], 1)]},
        )
    assert client.post(f"/api/tournament/{code}/rounds/close").status_code == 200


def pod_rooms(code):
    return [
        r["room_code"]
        for r in q(
            "SELECT p.room_code FROM pods p JOIN trounds r ON r.id = p.round_id "
            "WHERE r.tournament_code = ? AND p.room_code IS NOT NULL",
            (code,),
        ).fetchall()
    ]


def age_tournament(code, seconds):
    q("UPDATE tournaments SET last_active = unixepoch() - ? WHERE code = ?", (seconds, code))


def age_rooms(codes, seconds):
    for c in codes:
        q("UPDATE rooms SET last_active = unixepoch() - ? WHERE code = ?", (seconds, c))


def status_of(code):
    return q("SELECT status FROM tournaments WHERE code = ?", (code,)).fetchone()["status"]


class TestTournamentIdleExpiry:
    def test_the_constant_is_a_day_not_a_room(self, client):
        """The whole point of the tournament clock: it outlasts the room clock."""
        assert trn.IDLE_TIMEOUT > tbl.IDLE_TIMEOUT

    def test_an_idle_tournament_expires_on_read(self, client):
        organizer(client, "expOrgA")
        code = host(client)
        age_tournament(code, trn.IDLE_TIMEOUT + 60)
        state = client.get(f"/api/tournament/{code}").json()
        assert state["tournament"]["status"] == "expired"
        assert status_of(code) == "expired"

    def test_a_touched_tournament_survives(self, client):
        organizer(client, "expOrgB")
        code = host(client)
        age_tournament(code, trn.IDLE_TIMEOUT - 60)
        assert client.get(f"/api/tournament/{code}").json()["tournament"]["status"] == "setup"

    def test_activity_resets_the_clock(self, client):
        organizer(client, "expOrgC")
        code = host(client)
        age_tournament(code, trn.IDLE_TIMEOUT - 60)
        add(client, code, ["Ada"])  # organizer activity touches the tournament
        row = q("SELECT last_active FROM tournaments WHERE code = ?", (code,)).fetchone()
        now = q("SELECT unixepoch() n").fetchone()["n"]
        assert now - row["last_active"] < 5

    def test_expired_is_not_ended(self, client):
        """An organizer's decision and the server's hygiene are different facts."""
        organizer(client, "expOrgD")
        ended = host(client)
        client.post(f"/api/tournament/{ended}/end")
        expired = host(client)
        age_tournament(expired, trn.IDLE_TIMEOUT + 60)
        client.get(f"/api/tournament/{expired}")
        assert status_of(ended) == "ended"
        assert status_of(expired) == "expired"

    def test_an_expired_tournament_still_reads(self, client):
        """History and standings outlive the event — expiry closes play, not the book."""
        organizer(client, "expOrgE")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        open_round(client, code)
        finish_round(client, code)
        age_tournament(code, trn.IDLE_TIMEOUT + 60)
        r = client.get(f"/api/tournament/{code}")
        assert r.status_code == 200
        assert len(r.json()["standings"]) == 4

    def test_an_expired_tournament_cannot_open_a_round(self, client):
        organizer(client, "expOrgF")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        age_tournament(code, trn.IDLE_TIMEOUT + 60)
        r = client.post(f"/api/tournament/{code}/rounds", json={})
        assert r.status_code == 409
        assert "expired" in r.json()["detail"]

    def test_the_sweep_expires_tournaments_nobody_read(self, client):
        """Bulk hygiene, same shape as the room sweep: it runs on create."""
        organizer(client, "expOrgG")
        stale = host(client)
        age_tournament(stale, trn.IDLE_TIMEOUT + 60)
        host(client, "another event")  # POST /tournament sweeps
        assert status_of(stale) == "expired"

    def test_mine_does_not_list_an_abandoned_event_as_live(self, client):
        organizer(client, "expOrgH")
        code = host(client)
        age_tournament(code, trn.IDLE_TIMEOUT + 60)
        listed = {t["code"]: t for t in client.get("/api/tournament/mine").json()["tournaments"]}
        assert listed[code]["status"] == "expired"


class TestPodRoomExemption:
    def test_a_live_tournaments_pods_survive_the_room_sweep(self, client):
        """Lunch: the room clock runs out, the tournament's has not."""
        organizer(client, "podOrgA")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        open_round(client, code)
        rooms = pod_rooms(code)
        assert rooms
        age_rooms(rooms, tbl.IDLE_TIMEOUT + 60)
        tbl.expire_idle_rooms()
        for rc in rooms:
            assert tbl.get_room(rc)["status"] != "closed"

    def test_the_bulk_sweep_and_the_single_room_read_agree(self, client):
        """Both expiry paths, not just get_room, have to know about pods."""
        organizer(client, "podOrgB")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        open_round(client, code)
        rooms = pod_rooms(code)
        age_rooms(rooms, tbl.IDLE_TIMEOUT + 60)
        client.post("/api/table/rooms", json={"name": "sweeper", "mode": "life"})  # creating a room sweeps
        for rc in rooms:
            assert q("SELECT status FROM rooms WHERE code = ?", (rc,)).fetchone()["status"] != "closed"

    def test_expiring_a_tournament_hands_its_rooms_back_to_the_sweep(self, client):
        """The trap: an expired event whose rooms stay exempt lives forever."""
        organizer(client, "podOrgC")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        open_round(client, code)
        rooms = pod_rooms(code)
        age_rooms(rooms, tbl.IDLE_TIMEOUT + 60)
        age_tournament(code, trn.IDLE_TIMEOUT + 60)
        trn.expire_idle_tournaments()
        tbl.expire_idle_rooms()
        for rc in rooms:
            assert q("SELECT status FROM rooms WHERE code = ?", (rc,)).fetchone()["status"] == "closed"

    def test_an_idle_tournaments_rooms_expire_even_before_it_is_read(self, client):
        """The room sweep asks the tournament's clock directly, so it does not
        depend on anybody having read the tournament first."""
        organizer(client, "podOrgD")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        open_round(client, code)
        rooms = pod_rooms(code)
        age_rooms(rooms, tbl.IDLE_TIMEOUT + 60)
        age_tournament(code, trn.IDLE_TIMEOUT + 60)
        tbl.expire_idle_rooms()
        for rc in rooms:
            assert q("SELECT status FROM rooms WHERE code = ?", (rc,)).fetchone()["status"] == "closed"

    def test_an_ended_tournaments_rooms_lose_the_exemption(self, client):
        organizer(client, "podOrgE")
        code = host(client)
        add(client, code, ["Ada", "Grace", "Alan", "Edsger"])
        open_round(client, code)
        rooms = pod_rooms(code)
        finish_round(client, code)
        assert client.post(f"/api/tournament/{code}/end").status_code == 200
        age_rooms(rooms, tbl.IDLE_TIMEOUT + 60)
        tbl.expire_idle_rooms()
        for rc in rooms:
            assert q("SELECT status FROM rooms WHERE code = ?", (rc,)).fetchone()["status"] == "closed"

    def test_a_plain_room_is_never_exempt(self, client):
        r = client.post("/api/table/rooms", json={"name": "sweeper", "mode": "life"}).json()
        age_rooms([r["code"]], tbl.IDLE_TIMEOUT + 60)
        tbl.expire_idle_rooms()
        assert q("SELECT status FROM rooms WHERE code = ?", (r["code"],)).fetchone()["status"] == "closed"
