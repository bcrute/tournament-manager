"""Budgeting the one unauthenticated door.

Three routes resolve a room invitation without any credential — joining,
finding your seat again, and taking it back. They share a budget of their own
because the shape of legitimate use is unlike anything else in the app: a whole
venue arrives at once, from one address, inside a couple of minutes.

The budget is deliberately generous. It is no longer what stands between an
attacker and a room — 128 bits of identifier is — so it exists against
flooding, not against guessing, and the failure that actually matters is
locking a store full of players out because they share a NAT.
"""

import pytest
from fastapi.testclient import TestClient

from app.db import q
from app.limits import DEFAULT_RULES, RateLimiter, classify
from conftest import deployment_file


class TestClassification:
    def test_every_anonymous_lookup_lands_in_its_own_class(self):
        for path in (
            "/api/table/rooms/join",
            "/api/table/rooms/seats",
            "/api/table/rooms/reclaim",
        ):
            assert classify(path, "POST") == "room_lookup", path

    def test_seat_discovery_is_no_longer_ordinary_traffic(self):
        """It was a GET, so it fell through to `normal` — nine hundred a
        minute, on a route that names every player at a table."""
        assert classify("/api/table/rooms/seats", "GET") == "room_lookup"

    def test_gameplay_is_untouched(self):
        assert classify("/api/table/rooms/AB123/life", "POST") == "normal"
        assert classify("/api/table/rooms/AB123/me", "GET") == "normal"

    def test_creating_a_room_is_still_sensitive_not_a_lookup(self):
        assert classify("/api/table/rooms", "POST") == "sensitive"


class TestTheBudget:
    def limiter(self):
        return RateLimiter(clock=lambda: self.now)

    def setup_method(self):
        self.now = 1_000_000.0

    def test_a_venue_full_of_players_fits(self):
        """Forty people join, and half of them fumble it once. They share one
        address, and none of them may lock out the rest."""
        lim = self.limiter()
        allowed = 0
        for _ in range(60):
            ok, _ = lim.check("one-venue-nat", "room_lookup")
            if ok:
                allowed += 1
            self.now += 1
        assert allowed == 60, "a legitimate venue was throttled"

    def test_the_budget_is_what_the_rules_say(self):
        assert DEFAULT_RULES["room_lookup"] == (120, 300)

    def test_a_flood_is_eventually_refused_with_a_wait(self):
        lim = self.limiter()
        limit, _ = DEFAULT_RULES["room_lookup"]
        for _ in range(limit):
            assert lim.check("flooder", "room_lookup")[0] is True
        ok, retry = lim.check("flooder", "room_lookup")
        assert ok is False
        assert retry and retry > 0, "a refusal must say how long to wait"

    def test_the_window_rolls_forward(self):
        lim = self.limiter()
        limit, window = DEFAULT_RULES["room_lookup"]
        for _ in range(limit):
            lim.check("patient", "room_lookup")
        assert lim.check("patient", "room_lookup")[0] is False
        self.now += window + 1
        assert lim.check("patient", "room_lookup")[0] is True

    def test_one_client_flooding_does_not_spend_anybody_else_s_budget(self):
        """No per-room limit and no shared pool: an attacker must not be able
        to deny a room to the people actually at it."""
        lim = self.limiter()
        limit, _ = DEFAULT_RULES["room_lookup"]
        for _ in range(limit + 20):
            lim.check("flooder", "room_lookup")
        assert lim.check("someone-else", "room_lookup")[0] is True

    def test_the_buckets_are_independent(self):
        """Spending the whole lookup budget must not touch gameplay. Note the
        limit exactly, not past it: going over earns strikes, and enough
        strikes is a ban that applies to everything — which is the intended
        answer to a flood, and a different behaviour from bucket accounting."""
        lim = self.limiter()
        for _ in range(DEFAULT_RULES["room_lookup"][0]):
            assert lim.check("busy", "room_lookup")[0] is True
        assert lim.check("busy", "normal")[0] is True

    def test_a_sustained_flood_escalates_to_a_ban_across_the_board(self):
        """The existing escalation, reached through the new class."""
        from app.limits import STRIKES_BEFORE_BAN

        lim = self.limiter()
        limit, _ = DEFAULT_RULES["room_lookup"]
        for _ in range(limit + STRIKES_BEFORE_BAN):
            lim.check("determined", "room_lookup")
        ok, retry = lim.check("determined", "normal")
        assert ok is False, "a client that floods the door stays out of the house"
        assert retry > 0


@pytest.fixture(scope="module")
def app_client():
    """The real application, because the limiter is middleware installed there
    — a bare router has nothing to strike against."""
    from app.main import app as real_app

    with TestClient(real_app) as c:
        yield c


class TestStrikesInPractice:
    """Failures feed the existing escalation; successes do not."""

    def test_a_wrong_identifier_is_a_strike(self, app_client):
        from app.limits import client_id

        lim = app_client.app.state.limiter
        cid = client_id("testclient")
        before = len(lim._strikes.get(cid, []))
        app_client.post("/api/table/rooms/join",
                        json={"roomId": "nosuchroomatallxxxxxx", "name": "x", "display": False})
        assert len(lim._strikes.get(cid, [])) == before + 1

    def test_seat_discovery_strikes_too(self, app_client):
        """It did not, which is what made it the softer way in."""
        from app.limits import client_id

        lim = app_client.app.state.limiter
        cid = client_id("testclient")
        before = len(lim._strikes.get(cid, []))
        app_client.post("/api/table/rooms/seats", json={"roomId": "nosuchroomatallxxxxxx"})
        assert len(lim._strikes.get(cid, [])) == before + 1

    def test_a_successful_join_is_not_abuse(self, app_client):
        from app.limits import client_id

        made = app_client.post("/api/table/rooms",
                               json={"name": "host", "mode": "life"}).json()
        lim = app_client.app.state.limiter
        cid = client_id("testclient")
        before = len(lim._strikes.get(cid, []))
        r = app_client.post("/api/table/rooms/join",
                            json={"roomId": made["urlId"], "name": "guest", "display": False})
        assert r.status_code == 200
        assert len(lim._strikes.get(cid, [])) == before

    def test_a_couple_of_mistakes_do_not_ban_anyone(self, app_client):
        """Wrong links get pasted. Two of them is a person, not an attack."""
        from app.limits import client_id

        lim = app_client.app.state.limiter
        cid = client_id("testclient")
        lim._strikes.pop(cid, None)
        lim._bans.pop(cid, None)
        for _ in range(2):
            app_client.post("/api/table/rooms/join",
                            json={"roomId": "wrongbutplausiblexxxx", "name": "x", "display": False})
        made = app_client.post("/api/table/rooms",
                               json={"name": "host", "mode": "life"}).json()
        r = app_client.post("/api/table/rooms/join",
                            json={"roomId": made["urlId"], "name": "guest", "display": False})
        assert r.status_code == 200, "two fumbles must not lock somebody out"

    def test_the_security_log_records_the_client_not_the_identifier(self, app_client):
        """A room identifier is a credential. Logging the attempt is the point;
        logging what was attempted would put credentials in the log."""
        secret = "supersecretroomidxxxx"
        app_client.post("/api/table/rooms/join",
                        json={"roomId": secret, "name": "x", "display": False})
        rows = q("SELECT kind, subject, detail FROM security_log "
                 "ORDER BY id DESC LIMIT 10").fetchall()
        assert any(r["kind"] == "join.unknown_room" for r in rows)
        for r in rows:
            assert secret not in (r["subject"] or "")
            assert secret not in (r["detail"] or "")


class TestTheTrustBoundary:
    """Why `X-Forwarded-For` is trusted at all.

    Not an assumption — these read the deployment. If a port gets published or
    the proxy is widened, the reasoning in `client_ip()` stops holding and one
    of these fails.
    """

    def compose(self):
        return deployment_file("docker-compose.yml").read_text()

    def test_the_app_publishes_no_ports(self):
        """The only route in is the proxy: nothing is mapped to the host, so
        nothing can reach uvicorn and set its own forwarded header."""
        text = self.compose()
        assert "ports:" not in text, "publishing a port bypasses Caddy and the header becomes a lie"

    def test_the_app_sits_only_on_the_proxy_network(self):
        assert "networks:" in self.compose()
        assert "- web" in self.compose()

    def test_the_proxy_only_trusts_private_sources(self):
        """Caddy ignores a client's own X-Forwarded-For by default; the root
        config extends trust only to requests arriving from private ranges, and
        an internet client's address is public."""
        text = deployment_file("deploy/caddy/Caddyfile").read_text()
        assert "trusted_proxies static private_ranges" in text
        assert "trusted_proxies static 0.0.0.0/0" not in text

    def test_the_client_hash_is_all_that_is_kept(self):
        from app.limits import client_id

        ip = "203.0.113.7"
        cid = client_id(ip)
        assert ip not in cid
        assert cid == client_id(ip)
        assert cid != client_id("203.0.113.8")
