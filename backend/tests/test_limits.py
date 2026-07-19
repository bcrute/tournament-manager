"""Rate limiting, strike escalation and bans."""

import pytest

from app.limits import (
    BAN_STEPS,
    STRIKES_BEFORE_BAN,
    RateLimiter,
    classify,
    client_id,
)


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limiter(clock):
    # tight rules so the tests are quick and explicit
    return RateLimiter(rules={"normal": (3, 60), "sensitive": (2, 60), "socket": (2, 60)}, clock=clock)


class TestIdentity:
    def test_client_id_is_stable_and_not_the_ip(self):
        a = client_id("203.0.113.7")
        assert a == client_id("203.0.113.7")
        assert "203.0.113.7" not in a
        assert len(a) == 32

    def test_different_ips_get_different_ids(self):
        assert client_id("203.0.113.7") != client_id("203.0.113.8")


class TestWindow:
    def test_allows_up_to_the_limit(self, limiter):
        for _ in range(3):
            assert limiter.check("c", "normal")[0] is True

    def test_blocks_past_the_limit(self, limiter):
        for _ in range(3):
            limiter.check("c", "normal")
        allowed, retry = limiter.check("c", "normal")
        assert allowed is False and retry >= 1

    def test_window_slides(self, limiter, clock):
        for _ in range(3):
            limiter.check("c", "normal")
        assert limiter.check("c", "normal")[0] is False
        clock.advance(61)
        assert limiter.check("c", "normal")[0] is True

    def test_classes_have_separate_budgets(self, limiter):
        for _ in range(3):
            limiter.check("c", "normal")
        assert limiter.check("c", "sensitive")[0] is True

    def test_clients_are_independent(self, limiter):
        for _ in range(3):
            limiter.check("a", "normal")
        assert limiter.check("b", "normal")[0] is True


class TestBans:
    def test_repeated_violations_earn_a_ban(self, limiter, clock):
        for _ in range(3):
            limiter.check("c", "normal")
        for _ in range(STRIKES_BEFORE_BAN):
            limiter.check("c", "normal")  # each refusal is a strike
        assert limiter.ban_until("c") is not None
        # a ban applies across every route class, not just the abused one
        assert limiter.check("c", "sensitive")[0] is False

    def test_ban_expires(self, limiter, clock):
        for _ in range(3 + STRIKES_BEFORE_BAN):
            limiter.check("c", "normal")
        assert limiter.ban_until("c") is not None
        clock.advance(BAN_STEPS[0] + 1)
        assert limiter.ban_until("c") is None
        assert limiter.check("c", "normal")[0] is True

    def test_retry_after_counts_down_the_ban(self, limiter):
        for _ in range(3 + STRIKES_BEFORE_BAN):
            limiter.check("c", "normal")
        _, retry = limiter.check("c", "normal")
        assert 0 < retry <= BAN_STEPS[0]

    def test_strikes_expire_so_slow_offenders_are_not_banned(self, limiter, clock):
        for _ in range(3):
            limiter.check("c", "normal")
        for _ in range(STRIKES_BEFORE_BAN - 1):
            limiter.check("c", "normal")
            clock.advance(400)  # spread out beyond the strike window
        assert limiter.ban_until("c") is None

    def test_escalation_survives_an_expired_ban(self, limiter, clock):
        """Regression: expiring a ban used to wipe its record, so a repeat
        offender restarted at the shortest ban forever."""
        for _ in range(3 + STRIKES_BEFORE_BAN):
            limiter.check("c", "normal")
        first = limiter.ban_until("c") - clock()
        clock.advance(first + 1)
        for _ in range(3 + STRIKES_BEFORE_BAN):
            limiter.check("c", "normal")
        assert limiter.ban_until("c") - clock() > first

    def test_clear_lifts_a_ban(self, limiter):
        for _ in range(3 + STRIKES_BEFORE_BAN):
            limiter.check("c", "normal")
        limiter.clear("c")
        assert limiter.ban_until("c") is None


class TestPersistence:
    def test_bans_survive_a_restart(self, clock):
        from app.table import q

        first = RateLimiter(rules={"normal": (1, 60)}, clock=clock, db=q)
        for _ in range(1 + STRIKES_BEFORE_BAN):
            first.check("persisted-subject", "normal")
        assert first.ban_until("persisted-subject") is not None

        # a fresh limiter (as after a process restart) still knows
        second = RateLimiter(rules={"normal": (1, 60)}, clock=clock, db=q)
        assert second.ban_until("persisted-subject") is not None
        second.clear("persisted-subject")

    def test_repeat_offenders_climb_the_ladder(self, clock):
        from app.table import q

        lim = RateLimiter(rules={"normal": (1, 60)}, clock=clock, db=q)
        subject = "repeat-offender"
        lim.clear(subject)
        for _ in range(1 + STRIKES_BEFORE_BAN):
            lim.check(subject, "normal")
        first_len = lim.ban_until(subject) - clock()
        clock.advance(first_len + 1)
        for _ in range(1 + STRIKES_BEFORE_BAN):
            lim.check(subject, "normal")
        second_len = lim.ban_until(subject) - clock()
        assert second_len > first_len
        lim.clear(subject)


class TestClassification:
    def test_reads_are_normal(self):
        assert classify("/api/table/rooms/ABCDE/me", "GET") == "normal"

    def test_creation_and_seat_claims_are_sensitive(self):
        assert classify("/api/table/rooms", "POST") == "sensitive"
        assert classify("/api/table/rooms/ABCDE/join", "POST") == "sensitive"
        assert classify("/api/table/rooms/ABCDE/reclaim", "POST") == "sensitive"

    def test_gameplay_writes_are_normal(self):
        assert classify("/api/table/rooms/ABCDE/life", "POST") == "normal"
        assert classify("/api/table/rooms/ABCDE/cmddmg", "POST") == "normal"


class TestMemory:
    def test_prune_drops_idle_counters(self, limiter, clock):
        limiter.check("old", "normal")
        clock.advance(7200)
        limiter.check("new", "normal")
        limiter.prune(3600)
        assert not any(k[0] == "old" for k in limiter._hits)
        assert any(k[0] == "new" for k in limiter._hits)
