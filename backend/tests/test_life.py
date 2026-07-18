"""Life totals, commander damage, elimination."""


class TestLife:
    def test_self_adjust(self, api, life_room):
        code, tokens = life_room
        r = api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -7})
        assert r["life"] == 13
        assert api.me(code, tokens["p2"])["me"]["life"] == 13

    def test_zero_delta_is_noop(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": 0})
        assert api.me(code, tokens["p2"])["me"]["life"] == 20

    def test_life_can_go_negative(self, api, life_room):
        code, tokens = life_room
        r = api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -25})
        assert r["life"] == -5

    def test_no_adjust_in_lobby(self, api):
        r = api.create()
        api.call("POST", f"/rooms/{r['code']}/life", token=r["playerToken"], body={"delta": 1}, expect=409)

    def test_player_cannot_adjust_others(self, api, life_room):
        code, tokens = life_room
        api.call(
            "POST", f"/rooms/{code}/life", token=tokens["p2"],
            body={"delta": -99, "player": "p3"}, expect=403,
        )

    def test_display_adjusts_others(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        r = api.call("POST", f"/rooms/{code}/life", token=d, body={"delta": 3, "player": "p3"})
        assert r["life"] == 23

    def test_display_has_no_own_life(self, api, life_room):
        code, _ = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        api.call("POST", f"/rooms/{code}/life", token=d, body={"delta": 1}, expect=409)

    def test_display_adjust_unknown_player_404(self, api, life_room):
        code, _ = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        api.call("POST", f"/rooms/{code}/life", token=d, body={"delta": 1, "player": "ghost"}, expect=404)

    def test_life_change_logged(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -4})
        log = api.me(code, tokens["host"])["log"]
        assert any("p2: -4 life, 20 → 16" in e["text"] for e in log)


class TestCommanderDamage:
    def test_damage_accumulates_and_deducts_life(self, api, life_room):
        code, tokens = life_room
        r = api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p3", "delta": 5})
        assert r["total"] == 5 and r["life"] == 15 and r["lethal"] is False
        r = api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p3", "delta": 16})
        assert r["total"] == 21 and r["life"] == -1 and r["lethal"] is True

    def test_undo_restores_life_and_clamps_at_zero(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p3", "delta": 3})
        r = api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p3", "delta": -10})
        assert r["total"] == 0 and r["life"] == 20  # clamped: only 3 undone

    def test_per_attacker_tracking(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p3", "delta": 2})
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "host", "delta": 7})
        me = api.me(code, tokens["p2"])["me"]
        assert me["cmdDamage"] == {"p3": 2, "host": 7}
        assert me["life"] == 11

    def test_self_attacker_rejected(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p2", "delta": 1}, expect=400)

    def test_unknown_attacker_rejected(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "ghost", "delta": 1}, expect=400)

    def test_cmd_damage_visible_to_all(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attacker": "p3", "delta": 4})
        s = api.me(code, tokens["host"])
        p2 = next(p for p in s["players"] if p["name"] == "p2")
        assert p2["cmdDamage"] == {"p3": 4}


class TestEliminate:
    def test_eliminate_and_undo(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p2"], body={})
        s = api.me(code, tokens["host"])
        assert next(p for p in s["players"] if p["name"] == "p2")["eliminated"] is True
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p2"], body={"undo": True})
        s = api.me(code, tokens["host"])
        assert next(p for p in s["players"] if p["name"] == "p2")["eliminated"] is False

    def test_no_eliminate_in_lobby(self, api):
        r = api.create()
        api.call("POST", f"/rooms/{r['code']}/eliminate", token=r["playerToken"], body={}, expect=409)
