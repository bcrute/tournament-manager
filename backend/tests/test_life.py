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
            body={"delta": -99, "playerPid": api.pid_of(code, tokens["p2"], "p3")}, expect=403,
        )

    def test_display_adjusts_others(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        r = api.call("POST", f"/rooms/{code}/life", token=d, body={"delta": 3, "playerPid": api.pid_of(code, d, "p3")})
        assert r["life"] == 23

    def test_display_has_no_own_life(self, api, life_room):
        code, _ = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        api.call("POST", f"/rooms/{code}/life", token=d, body={"delta": 1}, expect=409)

    def test_display_adjust_unknown_player_404(self, api, life_room):
        code, _ = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        api.call("POST", f"/rooms/{code}/life", token=d, body={"delta": 1, "playerPid": 999999}, expect=404)

    def test_life_change_logged(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -4})
        log = api.me(code, tokens["host"])["log"]
        assert any("p2: -4 life, 20 → 16" in e["text"] for e in log)


class TestCommanderDamage:
    def test_damage_accumulates_and_deducts_life(self, api, life_room):
        code, tokens = life_room
        r = api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": api.pid_of(code, tokens["host"], "p3"), "delta": 5})
        assert r["total"] == 5 and r["life"] == 15 and r["lethal"] is False
        r = api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": api.pid_of(code, tokens["host"], "p3"), "delta": 16})
        assert r["total"] == 21 and r["life"] == -1 and r["lethal"] is True

    def test_undo_restores_life_and_clamps_at_zero(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": api.pid_of(code, tokens["host"], "p3"), "delta": 3})
        r = api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": api.pid_of(code, tokens["host"], "p3"), "delta": -10})
        assert r["total"] == 0 and r["life"] == 20  # clamped: only 3 undone

    def test_per_attacker_tracking(self, api, life_room):
        code, tokens = life_room
        p3_pid = api.pid_of(code, tokens["host"], "p3")
        host_pid = api.pid_of(code, tokens["host"], "host")
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": p3_pid, "delta": 2})
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": host_pid, "delta": 7})
        me = api.me(code, tokens["p2"])["me"]
        assert me["cmdDamage"] == {str(p3_pid): 2, str(host_pid): 7}
        assert me["life"] == 11

    def test_own_commander_can_damage_you(self, api, life_room):
        """Mind-control effects mean your own commander can hit you."""
        code, tokens = life_room
        p2_pid = api.pid_of(code, tokens["host"], "p2")
        r = api.call(
            "POST", f"/rooms/{code}/cmddmg", token=tokens["p2"],
            body={"attackerPid": p2_pid, "delta": 6},
        )
        assert r["total"] == 6 and r["life"] == 14
        assert api.me(code, tokens["p2"])["me"]["cmdDamage"] == {str(p2_pid): 6}

    def test_self_commander_damage_is_lethal_at_21(self, api, life_room):
        code, tokens = life_room
        p2_pid = api.pid_of(code, tokens["host"], "p2")
        r = api.call(
            "POST", f"/rooms/{code}/cmddmg", token=tokens["p2"],
            body={"attackerPid": p2_pid, "delta": 21},
        )
        assert r["lethal"] is True

    def test_unknown_attacker_rejected(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": 999999, "delta": 1}, expect=400)

    def test_cmd_damage_visible_to_all(self, api, life_room):
        code, tokens = life_room
        p3_pid = api.pid_of(code, tokens["host"], "p3")
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": p3_pid, "delta": 4})
        s = api.me(code, tokens["host"])
        p2 = next(p for p in s["players"] if p["name"] == "p2")
        assert p2["cmdDamage"] == {str(p3_pid): 4}


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
