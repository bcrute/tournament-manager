"""What a treachery deal puts on the table, and what it clears off it.

The Leader starts face up and known to everyone from turn one, so this table
gives them a cushion. **That is a house rule.** Rule 907.6 gives every player
the same starting total and says nothing about the Leader; nothing here should
be read as the variant asking for it, and `RulesSheet` says so in the same
words rather than implying otherwise.

The rest is about state that must not survive a game: poison counters and an
"I can't lose" flag are true of a board, and the board is gone.
"""

from app.db import q
from app.table import LEADER_BONUS_LIFE


def state(api, code, token):
    return api.me(code, token)


def by_name(api, code, token):
    return {p["name"]: p for p in api.me(code, token)["players"]}


def leader_name(code):
    row = q(
        "SELECT p.name FROM players p JOIN rooms r ON r.code = p.room_code "
        "WHERE p.room_code = ? AND p.id = r.first_pid",
        (code,),
    ).fetchone()
    return row["name"] if row else None


class TestTheLeadersCushion:
    def test_the_leader_starts_above_everyone_else(self, api, treachery_room):
        code, tok = treachery_room
        players = by_name(api, code, tok["host"])
        leader = leader_name(code)
        assert leader is not None

        room = api.me(code, tok["host"])["room"]
        assert players[leader]["life"] == room["startingLife"] + LEADER_BONUS_LIFE
        for name, p in players.items():
            if name != leader:
                assert p["life"] == room["startingLife"], f"{name} should be on the table total"

    def test_that_is_fifty_at_the_treachery_default(self, api, treachery_room):
        """40 is the default for a treachery table, so the Leader is on 50 —
        which is the number this was asked for in."""
        code, tok = treachery_room
        assert api.me(code, tok["host"])["room"]["startingLife"] == 40
        assert by_name(api, code, tok["host"])[leader_name(code)]["life"] == 50

    def test_it_follows_the_table_total_rather_than_being_a_fixed_number(self, api):
        """A host who picks a shorter game gets a shorter game — the Leader
        keeps the same cushion, not a total that towers over the table."""
        r = api.create("host", "treachery")
        code, host = r["code"], r["playerToken"]
        for n in ("p2", "p3", "p4", "p5"):
            api.join(code, n)
        api.call("POST", f"/rooms/{code}/options", token=host, body={"startingLife": 20})
        api.start(code, host)
        room = api.me(code, host)["room"]
        assert room["startingLife"] == 20
        assert by_name(api, code, host)[leader_name(code)]["life"] == 20 + LEADER_BONUS_LIFE

    def test_a_life_counter_game_gives_nobody_a_bonus(self, api, life_room):
        """`first_pid` is whoever won the roll for first turn there — they are
        not a Leader and must not be treated as one."""
        code, tok = life_room
        room = api.me(code, tok["host"])["room"]
        for p in api.me(code, tok["host"])["players"]:
            assert p["life"] == room["startingLife"]


class TestANewGameStartsClean:
    def test_poison_does_not_survive_into_the_next_game(self, api, life_room):
        """Regression: poison persisted across a reopen, so a player who ended
        one game on nine counters began the next one tick from dying."""
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/poison", token=tok["p2"], body={"delta": 9})
        assert by_name(api, code, tok["host"])["p2"]["poison"] == 9

        api.call("POST", f"/rooms/{code}/end", token=tok["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tok["host"])
        assert by_name(api, code, tok["host"])["p2"]["poison"] == 0

        api.start(code, tok["host"])
        assert by_name(api, code, tok["host"])["p2"]["poison"] == 0

    def test_i_cannot_lose_does_not_survive_either(self, api, life_room):
        """It describes a permanent on a battlefield that no longer exists.
        Carrying it over would make that player unkillable all night — which
        only started to matter when the flag began suppressing death itself
        rather than just a warning."""
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": True})
        assert by_name(api, code, tok["host"])["p2"]["cantLose"] is True

        api.call("POST", f"/rooms/{code}/end", token=tok["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tok["host"])
        api.start(code, tok["host"])
        assert by_name(api, code, tok["host"])["p2"]["cantLose"] is False

    def test_and_the_thresholds_work_again_in_the_new_game(self, api, life_room):
        """The point of clearing the flag: the next game can kill you."""
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/cantlose", token=tok["p2"], body={"value": True})
        api.call("POST", f"/rooms/{code}/life", token=tok["p2"], body={"delta": -30})
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is False

        api.call("POST", f"/rooms/{code}/end", token=tok["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tok["host"])
        api.start(code, tok["host"])
        api.call("POST", f"/rooms/{code}/life", token=tok["p2"], body={"delta": -30})
        assert by_name(api, code, tok["host"])["p2"]["eliminated"] is True

    def test_life_is_restored_for_everyone(self, api, life_room):
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/life", token=tok["p2"], body={"delta": -5})
        api.call("POST", f"/rooms/{code}/end", token=tok["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tok["host"])
        api.start(code, tok["host"])
        room = api.me(code, tok["host"])["room"]
        assert all(p["life"] == room["startingLife"] for p in api.me(code, tok["host"])["players"])
