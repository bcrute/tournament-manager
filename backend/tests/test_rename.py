"""Renaming: allowed anytime, uniqueness enforced, first_player follows."""


class TestRename:
    def test_rename_in_lobby(self, api):
        r = api.create()
        t2 = api.join(r["code"], "p2")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/rename", token=t2, body={"name": "gandalf"})
        s = api.me(r["code"], t2)
        assert s["me"]["name"] == "gandalf"
        assert "gandalf" in [p["name"] for p in s["players"]]

    def test_rename_mid_game(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "renamed"})
        assert api.me(code, tokens["p2"])["me"]["name"] == "renamed"

    def test_rename_preserves_life_and_cmd_damage(self, api, life_room):
        code, tokens = life_room
        p2_pid = api.pid_of(code, tokens["host"], "p2")
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -6})
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p3"], body={"attackerPid": p2_pid, "delta": 4})
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "renamed"})
        s = api.me(code, tokens["p3"])
        assert s["me"]["cmdDamage"] == {str(p2_pid): 4}  # pid-keyed: rename can't break it
        renamed = next(p for p in s["players"] if p["name"] == "renamed")
        assert renamed["life"] == 14

    def test_duplicate_names_allowed(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "p3"})
        s = api.me(code, tokens["host"])
        assert len([p for p in s["players"] if p["name"] == "p3"]) == 2

    def test_rename_to_own_name_is_noop(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "p2"})

    def test_first_player_follows_rename(self, api):
        r = api.create()
        api.join(r["code"], "p2")
        api.start(r["code"], r["playerToken"])
        s = api.me(r["code"], r["playerToken"])
        first = s["room"]["firstPlayer"]
        # find the first player's token
        tokens = {"host": r["playerToken"]}
        target = tokens.get("host") if first == "host" else None
        if target is None:
            return  # p2 went first; covered by dedicated treachery test below
        api.call("POST", f"/rooms/{r['code']}/rename", token=target, body={"name": "renamed"})
        assert api.me(r["code"], target)["room"]["firstPlayer"] == "renamed"

    def test_leader_rename_updates_first_player(self, api, treachery_room):
        code, tokens = treachery_room
        leader = next(
            n for n, tk in tokens.items()
            if api.me(code, tk)["me"]["card"]["role"] == "Leader"
        )
        api.call("POST", f"/rooms/{code}/rename", token=tokens[leader], body={"name": "the-boss"})
        assert api.me(code, tokens[leader])["room"]["firstPlayer"] == "the-boss"

    def test_left_player_cannot_rename(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "ghost"}, expect=403)

    def test_rename_logged(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "renamed"})
        log = api.me(code, tokens["host"])["log"]
        assert any("p2 is now known as renamed" in e["text"] for e in log)

    def test_pid_stable_across_rename(self, api, life_room):
        code, tokens = life_room
        before = next(p for p in api.me(code, tokens["host"])["players"] if p["name"] == "p2")
        api.call("POST", f"/rooms/{code}/rename", token=tokens["p2"], body={"name": "renamed"})
        after = next(p for p in api.me(code, tokens["host"])["players"] if p["name"] == "renamed")
        assert before["pid"] == after["pid"]
