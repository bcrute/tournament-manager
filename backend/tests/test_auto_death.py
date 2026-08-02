"""Dying happens to you; staying alive is the thing you tap.

Players used to confirm their own death, which meant four people waiting for
one of them to notice the counter had crossed. Now the counters decide — life
at zero, twenty-one commander damage from a single source, ten poison — and the
player gets an "I'm not dead" button instead.

Two rules keep that from ending someone's game for them:

- A player who has said **"I can't lose"** is never killed automatically. The
  app cannot see the battlefield, and Platinum Angel, Solemnity and Phyrexian
  Unlife all make a counter stop meaning what it usually means.
- The death that **ends the game** waits `CONCLUDE_GRACE_SECONDS` first, because
  it is the only one that cannot be undone afterwards.
"""

import pytest

from app.db import q
from app.table import CONCLUDE_GRACE_SECONDS, LETHAL_POISON


def alive(api, code, token):
    return {p["name"]: not p["eliminated"] for p in api.me(code, token)["players"]}


def poison(api, code, token, delta, pid=None, expect=200):
    body = {"delta": delta}
    if pid is not None:
        body["playerPid"] = pid
    return api.call("POST", f"/rooms/{code}/poison", token=token, body=body, expect=expect)


def life(api, code, token, delta, pid=None, expect=200):
    body = {"delta": delta}
    if pid is not None:
        body["playerPid"] = pid
    return api.call("POST", f"/rooms/{code}/life", token=token, body=body, expect=expect)


def cmd(api, code, token, attacker_pid, delta, defender_pid=None, expect=200):
    body = {"attackerPid": attacker_pid, "delta": delta}
    if defender_pid is not None:
        body["defenderPid"] = defender_pid
    return api.call("POST", f"/rooms/{code}/cmddmg", token=token, body=body, expect=expect)


class TestLifeReachesZero:
    def test_zero_life_eliminates_without_being_asked(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        assert alive(api, code, tok["host"])["p2"] is False

    def test_below_zero_counts_too(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -25)
        assert alive(api, code, tok["host"])["p2"] is False

    def test_one_life_is_still_alive(self, api, life_room):
        """The threshold is zero, not 'nearly zero'."""
        code, tok = life_room
        life(api, code, tok["p2"], -19)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_the_table_display_can_kill_someone_by_correcting_them(self, api):
        """A player whose phone is dead is still tracked by the table."""
        r = api.create("host", "life")
        code, host = r["code"], r["playerToken"]
        api.join(code, "p2")
        disp = api.join(code, "screen", display=True)["playerToken"]
        api.start(code, host)
        pid = api.pid_of(code, host, "p2")
        life(api, code, disp, -20, pid=pid)
        assert alive(api, code, host)["p2"] is False

    def test_gaining_life_back_brings_you_in_again(self, api, life_room):
        """This used to assert the opposite — that coming back was a decision
        rather than a side effect of a +5. Reviving by giving life replaced the
        menu that used to be the only way, so touching a dead player's total is
        now the statement. Fully covered in `test_revive_by_adjusting.py`; kept
        here so the old expectation can't quietly return."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        assert alive(api, code, tok["host"])["p2"] is False
        life(api, code, tok["p2"], 5)
        assert alive(api, code, tok["host"])["p2"] is True


class TestCommanderDamage:
    def test_twenty_one_from_one_source_eliminates(self, api, life_room):
        code, tok = life_room
        host_pid = api.pid_of(code, tok["p2"], "host")
        cmd(api, code, tok["p2"], host_pid, 21)
        assert alive(api, code, tok["host"])["p2"] is False

    def test_twenty_from_one_source_does_not(self, api, life_room):
        """Given enough life to survive the damage itself — a life room starts
        at twenty, so without the cushion this measures the wrong threshold."""
        code, tok = life_room
        host_pid = api.pid_of(code, tok["p2"], "host")
        life(api, code, tok["p2"], 40)
        cmd(api, code, tok["p2"], host_pid, 20)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_damage_split_across_two_commanders_is_not_lethal_by_itself(self, api, life_room):
        """CR 903.10a is per-source. Twenty from each of two commanders is
        forty life gone, but it is not commander-damage death."""
        code, tok = life_room
        r = api.create("host", "life")
        big = r["code"]
        t_host = r["playerToken"]
        t_a = api.join(big, "a")["playerToken"]
        api.join(big, "b")
        api.start(big, t_host)
        a_pid = api.pid_of(big, t_host, "a")
        b_pid = api.pid_of(big, t_host, "b")
        # start high enough that the life loss alone doesn't do it
        life(api, big, t_a, 60)
        cmd(api, big, t_a, a_pid, 15)
        cmd(api, big, t_a, b_pid, 15)
        assert alive(api, big, t_host)["a"] is True

    def test_the_life_the_damage_took_can_be_what_kills_you(self, api, life_room):
        """Commander damage is damage: 20 from one source is not 21, but it
        still took twenty life, and twenty life is the whole total."""
        code, tok = life_room
        host_pid = api.pid_of(code, tok["p2"], "host")
        cmd(api, code, tok["p2"], host_pid, 20)
        assert alive(api, code, tok["host"])["p2"] is False


class TestPoison:
    def test_ten_poison_eliminates(self, api, life_room):
        code, tok = life_room
        poison(api, code, tok["p2"], LETHAL_POISON)
        assert alive(api, code, tok["host"])["p2"] is False

    def test_nine_does_not(self, api, life_room):
        code, tok = life_room
        poison(api, code, tok["p2"], LETHAL_POISON - 1)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_counters_accumulate(self, api, life_room):
        code, tok = life_room
        for _ in range(5):
            poison(api, code, tok["p2"], 2)
        assert alive(api, code, tok["host"])["p2"] is False

    def test_poison_is_reported_in_state(self, api, life_room):
        code, tok = life_room
        poison(api, code, tok["p2"], 3)
        state = api.me(code, tok["p2"])
        assert state["me"]["poison"] == 3
        assert next(p["poison"] for p in state["players"] if p["name"] == "p2") == 3

    def test_everyone_starts_at_zero(self, api, life_room):
        code, tok = life_room
        assert all(p["poison"] == 0 for p in api.me(code, tok["host"])["players"])

    def test_counters_never_go_negative(self, api, life_room):
        code, tok = life_room
        poison(api, code, tok["p2"], 2)
        assert poison(api, code, tok["p2"], -5)["poison"] == 0

    def test_a_display_has_no_counters_of_its_own(self, api):
        r = api.create("host", "life")
        code, host = r["code"], r["playerToken"]
        api.join(code, "p2")
        disp = api.join(code, "screen", display=True)["playerToken"]
        api.start(code, host)
        poison(api, code, disp, 1, expect=409)

    def test_an_ordinary_player_cannot_poison_someone_else(self, api, life_room):
        """Same rule as life: only the display or a player keeping score."""
        code, tok = life_room
        pid = api.pid_of(code, tok["host"], "p2")
        poison(api, code, tok["p3"], 10, pid=pid, expect=403)


class TestCantLoseIsNeverOverridden:
    def test_zero_life_does_not_kill_a_player_who_cannot_lose(self, api, life_room):
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": True})
        life(api, code, tok["p2"], -20)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_nor_does_commander_damage(self, api, life_room):
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": True})
        cmd(api, code, tok["p2"], api.pid_of(code, tok["p2"], "host"), 25)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_nor_does_poison(self, api, life_room):
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": True})
        poison(api, code, tok["p2"], 20)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_turning_it_off_does_not_retroactively_kill_them(self, api, life_room):
        """Clearing the flag re-arms the check; it does not run it. The next
        actual change decides, which is the same rule as everywhere else."""
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": True})
        life(api, code, tok["p2"], -20)
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": False})
        assert alive(api, code, tok["host"])["p2"] is True
        life(api, code, tok["p2"], -1)
        assert alive(api, code, tok["host"])["p2"] is False


class TestImNotDead:
    def test_it_brings_them_back_and_stops_the_app_asking_again(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p2"], body={"undo": True})
        state = api.me(code, tok["p2"])
        assert state["me"]["eliminated"] is False
        assert state["me"]["cantLose"] is True

    def test_and_the_next_change_does_not_kill_them_again(self, api, life_room):
        """The whole point: they are still on zero life. Without the flag they
        would be arguing with the app once per turn."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p2"], body={"undo": True})
        life(api, code, tok["p2"], -1)
        assert alive(api, code, tok["host"])["p2"] is True

    def test_a_death_the_counters_did_not_call_leaves_the_flag_alone(self, api, life_room):
        """Someone decked at twenty life has nothing to suppress, and marking
        them unable to lose would be inventing a board state they never had."""
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p2"], body={"undo": False})
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p2"], body={"undo": True})
        state = api.me(code, tok["p2"])
        assert state["me"]["eliminated"] is False
        assert state["me"]["cantLose"] is False

    def test_the_table_display_reviving_someone_works_the_same_way(self, api):
        """The reason the server decides instead of the client asking: a player
        whose phone is flat is brought back by the display, and that revive has
        exactly the same problem — still on zero life, dead again next tap."""
        r = api.create("host", "life")
        code, host = r["code"], r["playerToken"]
        api.join(code, "p2")
        disp = api.join(code, "screen", display=True)["playerToken"]
        api.start(code, host)
        pid = api.pid_of(code, host, "p2")
        life(api, code, disp, -20, pid=pid)
        assert alive(api, code, host)["p2"] is False

        api.call(
            "POST", f"/rooms/{code}/eliminate", token=disp,
            body={"undo": True, "playerPid": pid},
        )
        p2 = next(p for p in api.me(code, host)["players"] if p["name"] == "p2")
        assert p2["eliminated"] is False
        assert p2["cantLose"] is True
        life(api, code, disp, -1, pid=pid)
        assert alive(api, code, host)["p2"] is True


class TestTheLastDeathWaits:
    """The only elimination that cannot be undone afterwards."""

    def pending(self, code):
        return q("SELECT concludes_at FROM rooms WHERE code = ?", (code,)).fetchone()[
            "concludes_at"
        ]

    def test_a_game_ending_death_does_not_end_the_game_yet(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)          # 3 -> 2 alive, game continues
        assert api.me(code, tok["host"])["room"]["status"] == "playing"
        life(api, code, tok["p3"], -20)          # 2 -> 1, this one would end it
        state = api.me(code, tok["host"])
        assert state["room"]["status"] == "playing", "the game ended without the grace window"
        assert state["room"]["concludesAt"] is not None

    def test_the_countdown_is_about_ten_seconds_away(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        state = api.me(code, tok["host"])
        remaining = state["room"]["concludesAt"] - state["room"]["now"]
        assert 0 < remaining <= CONCLUDE_GRACE_SECONDS

    def test_saying_youre_not_dead_calls_the_ending_off(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p3"], body={"undo": True})
        state = api.me(code, tok["host"])
        assert state["room"]["status"] == "playing"
        assert state["room"]["concludesAt"] is None
        assert self.pending(code) is None

    def test_the_game_ends_once_the_window_passes(self, api, life_room):
        """Driven by moving the deadline into the past rather than sleeping —
        the window is an absolute timestamp precisely so this is possible."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        q("UPDATE rooms SET concludes_at = unixepoch() - 1 WHERE code = ?", (code,))
        state = api.me(code, tok["host"])          # any read resolves it
        assert state["room"]["status"] == "ended"
        assert state["room"]["concludesAt"] is None

    def test_a_non_final_death_never_waits(self, api, life_room):
        """Three players, one dies: the game carries on and nothing is pending,
        because that death stays undoable for as long as the game runs."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        assert self.pending(code) is None

    def test_a_deliberate_death_ends_it_immediately(self, api, life_room):
        """"I lost some other way" is a decision, not a counter crossing. The
        app has nothing to be unsure about, so it does not stall."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p3"], body={"undo": False})
        state = api.me(code, tok["host"])
        assert state["room"]["status"] == "ended"
        assert state["room"]["concludesAt"] is None

    def test_a_second_death_inside_the_window_does_not_restart_it(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        first = self.pending(code)
        life(api, code, tok["host"], -20)   # the last player goes too
        assert self.pending(code) == first

    def test_coming_back_then_dying_again_starts_a_fresh_window(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        api.call("POST", f"/rooms/{code}/eliminate", token=tok["p3"], body={"undo": True})
        assert self.pending(code) is None
        life(api, code, tok["host"], -20)
        assert self.pending(code) is not None


class TestTournamentPlacementIsUnaffected:
    def test_placement_still_follows_elimination_order(self, api, life_room):
        """Auto-death writes the same `eliminated_at` the manual path did, so
        the order results are derived from is unchanged."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        q("UPDATE rooms SET concludes_at = unixepoch() - 1 WHERE code = ?", (code,))
        api.me(code, tok["host"])
        rows = q(
            "SELECT name, eliminated, eliminated_at FROM players WHERE room_code = ? "
            "AND is_display = 0 ORDER BY eliminated_at",
            (code,),
        ).fetchall()
        out = [r["name"] for r in rows if r["eliminated"]]
        assert out == ["p2", "p3"]
        assert [r["name"] for r in rows if not r["eliminated"]] == ["host"]


class TestTreachery:
    def test_an_automatic_death_still_reveals_the_identity(self, api, treachery_room):
        """CR 907.13 doesn't care how you died."""
        code, tok = treachery_room
        # more than any starting total: p2 may have been dealt the Leader, who
        # now begins on 50, and -40 would leave them standing
        life(api, code, tok["p2"], -99)
        p2 = next(p for p in api.me(code, tok["host"])["players"] if p["name"] == "p2")
        assert p2["eliminated"] is True
        assert p2["revealed"] is True
