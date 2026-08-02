"""Putting life back on a dead player brings them back.

Reviving used to be a menu on the table view, reached by holding a seat card.
Somebody reaching over to give an eliminated player life has already said what
they mean, so the adjustment is the revival.

It only carries when the counters agree. That guard is not politeness: an
elimination carries the moment it happened, and tournament placement is read
from the order of those moments. Clearing and re-stamping one on a stray tap
would silently reorder a pod's results.
"""

from app.db import q


def state(api, code, token):
    return api.me(code, token)


def by_name(api, code, token):
    return {p["name"]: p for p in api.me(code, token)["players"]}


def life(api, code, token, delta, pid=None, expect=200):
    body = {"delta": delta}
    if pid is not None:
        body["playerPid"] = pid
    return api.call("POST", f"/rooms/{code}/life", token=token, body=body, expect=expect)


def eliminated_at(code, name):
    return q(
        "SELECT eliminated_at FROM players WHERE room_code = ? AND name = ?", (code, name)
    ).fetchone()["eliminated_at"]


class TestGivingLifeBringsThemBack:
    def test_adding_life_revives_an_eliminated_player(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True

        life(api, code, tok["p2"], 5)
        p2 = by_name(api, code, tok["host"])["p2"]
        assert p2["eliminated"] is False
        assert p2["life"] == 5

    def test_the_table_display_can_do_it_for_them(self, api):
        """The case this replaces: a player whose phone is flat, brought back
        by whoever is holding the table view."""
        r = api.create("host", "life")
        code, host = r["code"], r["playerToken"]
        api.join(code, "p2")
        disp = api.join(code, "screen", display=True)["playerToken"]
        api.start(code, host)
        pid = api.pid_of(code, host, "p2")

        life(api, code, disp, -20, pid=pid)
        assert by_name(api, code, host)["p2"]["eliminated"] is True
        life(api, code, disp, 3, pid=pid)
        assert by_name(api, code, host)["p2"]["eliminated"] is False

    def test_it_clears_the_death_stamp_as_well(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        assert eliminated_at(code, "p2") is not None
        life(api, code, tok["p2"], 5)
        assert eliminated_at(code, "p2") is None

    def test_and_it_is_logged(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p2"], 5)
        log = [e["text"] for e in api.me(code, tok["host"])["log"]]
        assert any("p2 is back in the game" in t for t in log)


class TestOnlyWhenTheCountersAgree:
    def test_taking_more_life_away_leaves_them_out(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p2"], -1)
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True

    def test_and_does_not_move_their_place_in_the_death_order(self, api, life_room):
        """The reason for the guard. Placement is derived from these stamps."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        stamp = eliminated_at(code, "p2")
        life(api, code, tok["p2"], -1)
        life(api, code, tok["p2"], -1)
        assert eliminated_at(code, "p2") == stamp

    def test_adding_too_little_to_clear_zero_leaves_them_out(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -25)   # down to -5
        life(api, code, tok["p2"], 3)     # still -2
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True

    def test_life_alone_is_not_enough_when_poison_is_lethal(self, api, life_room):
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/poison", token=tok["p2"], body={"delta": 10})
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True
        life(api, code, tok["p2"], 5)
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True

    def test_nor_when_commander_damage_is(self, api, life_room):
        code, tok = life_room
        host_pid = api.pid_of(code, tok["p2"], "host")
        api.call(
            "POST", f"/rooms/{code}/cmddmg", token=tok["p2"],
            body={"attackerPid": host_pid, "delta": 21},
        )
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True
        life(api, code, tok["p2"], 40)
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True

    def test_a_living_player_is_untouched(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -1)
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is False


class TestItCallsOffTheEnding:
    def pending(self, code):
        return q("SELECT concludes_at FROM rooms WHERE code = ?", (code,)).fetchone()[
            "concludes_at"
        ]

    def test_reviving_the_last_death_stops_the_game_ending(self, api, life_room):
        """The ten-second window exists for exactly this — and putting life back
        is now one of the two ways to use it."""
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)          # would end the game
        assert self.pending(code) is not None

        life(api, code, tok["p3"], 6)
        assert self.pending(code) is None
        s = api.me(code, tok["host"])
        assert s["room"]["status"] == "playing"
        assert s["room"]["concludesAt"] is None

    def test_a_revive_that_does_not_take_leaves_the_countdown_running(self, api, life_room):
        code, tok = life_room
        life(api, code, tok["p2"], -20)
        life(api, code, tok["p3"], -20)
        first = self.pending(code)
        life(api, code, tok["p3"], -1)           # still lethal, still out
        assert self.pending(code) == first


class TestTreachery:
    def test_coming_back_does_not_re_hide_a_revealed_identity(self, api, treachery_room):
        """CR 907.13 revealed them on the way out; returning doesn't unsay it."""
        code, tok = treachery_room
        life(api, code, tok["p2"], -99)
        p2 = by_name(api, code, tok["host"])["p2"]
        assert p2["eliminated"] is True and p2["revealed"] is True

        life(api, code, tok["p2"], 60)
        p2 = by_name(api, code, tok["host"])["p2"]
        assert p2["eliminated"] is False
        assert p2["revealed"] is True
