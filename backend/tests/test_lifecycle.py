"""Last-player-standing auto-end and idle room expiry."""

import app.table as tbl
from app.table import q


class TestLastStanding:
    def test_game_ends_when_one_player_remains(self, api, life_room):
        code, tokens = life_room  # host, p2, p3
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p2"], body={})
        assert api.me(code, tokens["host"])["room"]["status"] == "playing"
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p3"], body={})
        s = api.me(code, tokens["host"])
        assert s["room"]["status"] == "ended"
        assert any("last player standing" in e["text"] for e in s["log"])

    def test_leaving_can_end_the_game_too(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p3"])
        assert api.me(code, tokens["host"])["room"]["status"] == "ended"

    def test_treachery_auto_end_reveals_and_logs_identities(self, api, treachery_room):
        code, tokens = treachery_room
        victims = [n for n in tokens if n != "host"]
        for n in victims:
            api.call("POST", f"/rooms/{code}/eliminate", token=tokens[n], body={})
        s = api.me(code, tokens["host"])
        assert s["room"]["status"] == "ended"
        assert all(p["card"] is not None for p in s["players"])
        assert len([e for e in s["log"] if e["text"].startswith("final identity:")]) == 5

    def test_undo_before_the_last_elimination_keeps_the_game_live(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p2"], body={})
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p2"], body={"undo": True})
        assert api.me(code, tokens["host"])["room"]["status"] == "playing"

    def test_display_does_not_count_as_a_player(self, api, life_room):
        code, tokens = life_room
        api.join(code, "tv", display=True)
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p2"], body={})
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p3"], body={})
        assert api.me(code, tokens["host"])["room"]["status"] == "ended"


class TestIdleExpiry:
    def test_idle_room_closes_and_rejects_access(self, api, monkeypatch):
        r = api.create()
        code, t = r["code"], r["playerToken"]
        q("UPDATE rooms SET last_active = unixepoch() - ? WHERE code = ?", (tbl.IDLE_TIMEOUT + 60, code))
        api.me(code, t, expect=410)
        api.join(code, "late", expect=410)

    def test_active_room_survives_the_sweep(self, api):
        r = api.create()
        code, t = r["code"], r["playerToken"]
        q("UPDATE rooms SET last_active = unixepoch() - ? WHERE code = ?", (tbl.IDLE_TIMEOUT - 60, code))
        assert api.me(code, t)["room"]["status"] == "lobby"

    def test_activity_resets_the_clock(self, api):
        r = api.create()
        code, t = r["code"], r["playerToken"]
        q("UPDATE rooms SET last_active = unixepoch() - ? WHERE code = ?", (tbl.IDLE_TIMEOUT - 60, code))
        api.join(code, "p2")  # activity
        q("UPDATE rooms SET last_active = last_active WHERE code = ?", (code,))
        row = q("SELECT last_active FROM rooms WHERE code = ?", (code,)).fetchone()
        now = q("SELECT unixepoch() n").fetchone()["n"]
        assert now - row["last_active"] < 5

    def test_history_survives_a_closed_room(self, api):
        """Closing frees the code, it must not erase the game history."""
        r = api.create()
        code = r["code"]
        before = q("SELECT COUNT(*) c FROM events WHERE room_code = ?", (code,)).fetchone()["c"]
        q("UPDATE rooms SET last_active = unixepoch() - ? WHERE code = ?", (tbl.IDLE_TIMEOUT + 60, code))
        api.me(code, r["playerToken"], expect=410)
        after = q("SELECT COUNT(*) c FROM events WHERE room_code = ?", (code,)).fetchone()["c"]
        assert after == before and before > 0
