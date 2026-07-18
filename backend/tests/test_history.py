"""Game history retention: events persist forever, segmented by game number."""

from app.table import q


class TestHistory:
    def test_events_stamped_with_game_number(self, api):
        r = api.create()
        code, t = r["code"], r["playerToken"]
        api.join(code, "p2")
        api.start(code, t)  # game 1
        api.call("POST", f"/rooms/{code}/end", token=t)
        api.call("POST", f"/rooms/{code}/reopen", token=t)
        api.start(code, t)  # game 2

        rows = q(
            "SELECT text, game_no FROM events WHERE room_code = ? ORDER BY id", (code,)
        ).fetchall()
        by_game = {}
        for row in rows:
            by_game.setdefault(row["game_no"], []).append(row["text"])
        # lobby events are game 0; each start opens a new segment
        assert 0 in by_game and any("created the room" in t for t in by_game[0])
        assert any("goes first" in t for t in by_game[1])
        assert any("ended the game" in t for t in by_game[2] + by_game[1])
        assert max(by_game) == 2

    def test_history_survives_reopen(self, api):
        """Regression: reopen must never delete past games' events."""
        r = api.create()
        code, t = r["code"], r["playerToken"]
        api.join(code, "p2")
        api.start(code, t)
        n_before = q("SELECT COUNT(*) c FROM events WHERE room_code = ?", (code,)).fetchone()["c"]
        api.call("POST", f"/rooms/{code}/end", token=t)
        api.call("POST", f"/rooms/{code}/reopen", token=t)
        n_after = q("SELECT COUNT(*) c FROM events WHERE room_code = ?", (code,)).fetchone()["c"]
        assert n_after > n_before

    def test_no_pii_in_history_schema(self):
        """The history tables must hold nothing beyond names, ids and game text."""
        cols = {r["name"] for r in q("PRAGMA table_info(events)").fetchall()}
        assert cols == {"id", "room_code", "at", "text", "game_no"}
        player_cols = {r["name"] for r in q("PRAGMA table_info(players)").fetchall()}
        forbidden = {"ip", "address", "location", "email", "user_agent"}
        assert not (player_cols & forbidden)
