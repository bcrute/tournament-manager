"""Room lifecycle: create, join, options, start, end, reopen, leave."""

from app.table import distribution


class TestCreate:
    def test_life_mode_defaults(self, api):
        r = api.create("ben", "life")
        assert len(r["code"]) == 5 and r["playerToken"]
        s = api.me(r["code"], r["playerToken"])
        assert s["room"]["mode"] == "life"
        assert s["room"]["status"] == "lobby"
        assert s["room"]["startingLife"] == 20
        assert s["me"]["isHost"] is True

    def test_treachery_mode_defaults_to_40_life(self, api):
        r = api.create("ben", "treachery")
        s = api.me(r["code"], r["playerToken"])
        assert s["room"]["mode"] == "treachery"
        assert s["room"]["startingLife"] == 40

    def test_unknown_mode_rejected(self, api):
        api.call("POST", "/rooms", body={"name": "x", "mode": "poker"}, expect=400)

    def test_empty_name_rejected(self, api):
        api.call("POST", "/rooms", body={"name": "", "mode": "life"}, expect=422)


class TestJoin:
    def test_join_and_roster(self, api):
        r = api.create()
        t2 = api.join(r["code"], "p2")["playerToken"]
        s = api.me(r["code"], t2)
        assert [p["name"] for p in s["players"]] == ["host", "p2"]
        assert s["me"]["isHost"] is False

    def test_duplicate_names_allowed_with_distinct_pids(self, api):
        r = api.create()
        t1 = api.join(r["code"], "bob")["playerToken"]
        t2 = api.join(r["code"], "bob")["playerToken"]
        s = api.me(r["code"], t1)
        bobs = [p for p in s["players"] if p["name"] == "bob"]
        assert len(bobs) == 2
        assert bobs[0]["pid"] != bobs[1]["pid"]
        # each token maps to its own player
        assert api.me(r["code"], t1)["me"]["pid"] != api.me(r["code"], t2)["me"]["pid"]

    def test_join_after_start_rejected(self, api, life_room):
        code, _ = life_room
        api.join(code, "latecomer", expect=409)

    def test_display_can_join_mid_game(self, api, life_room):
        code, _ = life_room
        d = api.join(code, "tv", display=True)
        s = api.me(code, d["playerToken"])
        assert s["me"]["isDisplay"] is True
        # displays are not part of the player roster
        assert "tv" not in [p["name"] for p in s["players"]]

    def test_display_counted_in_room(self, api):
        r = api.create()
        api.join(r["code"], "tv", display=True)
        s = api.me(r["code"], r["playerToken"])
        assert s["room"]["displays"] == 1

    def test_unknown_room_404(self, api):
        api.join("ZZZZZ", "x", expect=404)


class TestAuth:
    def test_missing_token_401(self, api):
        r = api.create()
        api.call("GET", f"/rooms/{r['code']}/me", expect=401)

    def test_wrong_token_403(self, api):
        r = api.create()
        api.call("GET", f"/rooms/{r['code']}/me", token="nope", expect=403)

    def test_token_from_other_room_403(self, api):
        r1 = api.create()
        r2 = api.create()
        api.me(r2["code"], r1["playerToken"], expect=403)


class TestOptions:
    def test_host_sets_starting_life(self, api):
        r = api.create()
        api.call("POST", f"/rooms/{r['code']}/options", token=r["playerToken"], body={"startingLife": 30})
        assert api.me(r["code"], r["playerToken"])["room"]["startingLife"] == 30

    def test_non_host_cannot_set_options(self, api):
        r = api.create()
        t2 = api.join(r["code"], "p2")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/options", token=t2, body={"startingLife": 30}, expect=403)

    def test_starting_life_locked_after_start(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/options", token=tokens["host"], body={"startingLife": 99}, expect=409)

    def test_starting_life_bounds(self, api):
        r = api.create()
        api.call("POST", f"/rooms/{r['code']}/options", token=r["playerToken"], body={"startingLife": 0}, expect=422)
        api.call("POST", f"/rooms/{r['code']}/options", token=r["playerToken"], body={"startingLife": 1000}, expect=422)


class TestStart:
    def test_start_sets_life_status_and_first_player(self, api):
        r = api.create()
        t2 = api.join(r["code"], "p2")["playerToken"]
        api.start(r["code"], r["playerToken"])
        s = api.me(r["code"], t2)
        assert s["room"]["status"] == "playing"
        assert s["room"]["firstPlayer"] in ("host", "p2")
        assert all(p["life"] == 20 for p in s["players"])

    def test_non_host_cannot_start(self, api):
        r = api.create()
        t2 = api.join(r["code"], "p2")["playerToken"]
        api.start(r["code"], t2, expect=403)

    def test_double_start_rejected(self, api, life_room):
        code, tokens = life_room
        api.start(code, tokens["host"], expect=409)

    def test_start_uses_configured_life(self, api):
        r = api.create()
        api.call("POST", f"/rooms/{r['code']}/options", token=r["playerToken"], body={"startingLife": 55})
        api.start(r["code"], r["playerToken"])
        assert api.me(r["code"], r["playerToken"])["me"]["life"] == 55


class TestEndReopen:
    def test_end_host_only(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/end", token=tokens["p2"], expect=403)
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        assert api.me(code, tokens["p2"])["room"]["status"] == "ended"

    def test_reopen_resets_state(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -5})
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens["p3"], body={})
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tokens["host"])
        s = api.me(code, tokens["p2"])
        assert s["room"]["status"] == "lobby"
        assert s["room"]["firstPlayer"] is None
        assert all(p["life"] is None and not p["eliminated"] for p in s["players"])


class TestLeave:
    def test_lobby_leave_removes_player(self, api):
        r = api.create()
        t2 = api.join(r["code"], "p2")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/leave", token=t2)
        s = api.me(r["code"], r["playerToken"])
        assert [p["name"] for p in s["players"]] == ["host"]

    def test_left_token_cannot_reenter(self, api, life_room):
        """Regression: leaving must invalidate the session server-side."""
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.me(code, tokens["p2"], expect=403)

    def test_midgame_leaver_shown_as_left(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        s = api.me(code, tokens["host"])
        p2 = next(p for p in s["players"] if p["name"] == "p2")
        assert p2["left"] is True

    def test_host_leaving_promotes_next_player(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["host"])
        s = api.me(code, tokens["p2"])
        assert s["me"]["isHost"] is True

    def test_display_leave_is_clean(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        api.call("POST", f"/rooms/{code}/leave", token=d)
        assert api.me(code, tokens["host"])["room"]["displays"] == 0


class TestDistribution:
    def test_official_table(self):
        assert distribution(4) == (1, 1, 2, 0)
        assert distribution(5) == (1, 1, 2, 1)
        assert distribution(6) == (1, 1, 3, 1)
        assert distribution(7) == (1, 1, 3, 2)
        assert distribution(8) == (1, 2, 3, 2)

    def test_small_and_large_fallbacks_sum_correctly(self):
        for n in (1, 2, 3, 9, 10, 12):
            ldr, trt, ass, gdn = distribution(n)
            assert ldr == 1
            assert ldr + trt + ass + gdn == n
            assert min(trt, ass, gdn) >= 0
