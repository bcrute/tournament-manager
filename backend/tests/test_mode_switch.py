"""Host can reconfigure the room in the lobby (mode + starting life)."""


class TestModeSwitch:
    def test_host_switches_mode_in_lobby(self, api):
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        api.call("POST", f"/rooms/{code}/options", token=t, body={"mode": "treachery"})
        s = api.me(code, t)
        assert s["room"]["mode"] == "treachery"
        assert s["room"]["startingLife"] == 40  # mode default follows

    def test_switching_back_restores_life_default(self, api):
        r = api.create("host", "treachery")
        code, t = r["code"], r["playerToken"]
        api.call("POST", f"/rooms/{code}/options", token=t, body={"mode": "life"})
        assert api.me(code, t)["room"]["startingLife"] == 20

    def test_custom_life_after_mode_switch_is_kept(self, api):
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        api.call("POST", f"/rooms/{code}/options", token=t, body={"mode": "treachery"})
        api.call("POST", f"/rooms/{code}/options", token=t, body={"startingLife": 25})
        assert api.me(code, t)["room"]["startingLife"] == 25

    def test_mode_and_life_in_one_call(self, api):
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        api.call("POST", f"/rooms/{code}/options", token=t, body={"mode": "treachery", "startingLife": 30})
        s = api.me(code, t)
        assert s["room"]["mode"] == "treachery" and s["room"]["startingLife"] == 30

    def test_non_host_cannot_switch_mode(self, api):
        r = api.create("host", "life")
        t2 = api.join(r["code"], "p2")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/options", token=t2, body={"mode": "treachery"}, expect=403)

    def test_cannot_switch_mode_after_start(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/options", token=tokens["host"], body={"mode": "treachery"}, expect=409)

    def test_unknown_mode_rejected(self, api):
        r = api.create("host", "life")
        api.call("POST", f"/rooms/{r['code']}/options", token=r["playerToken"], body={"mode": "poker"}, expect=400)

    def test_same_mode_is_noop(self, api, life_room):
        """Re-sending the current mode must not 409 even mid-game."""
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/options", token=tokens["host"], body={"mode": "life"})

    def test_mode_switch_logged(self, api):
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        api.call("POST", f"/rooms/{code}/options", token=t, body={"mode": "treachery"})
        log = [e["text"] for e in api.me(code, t)["log"]]
        assert any("switched the game to Treachery" in x for x in log)

    def test_switched_room_deals_treachery_identities(self, api):
        """End to end: a life room switched to treachery deals real identities."""
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        toks = [api.join(code, f"p{i}")["playerToken"] for i in range(2, 6)]
        api.call("POST", f"/rooms/{code}/options", token=t, body={"mode": "treachery"})
        api.start(code, t)
        roles = sorted(
            api.me(code, tk)["me"]["card"]["role"] for tk in [t, *toks]
        )
        assert roles == ["Assassin", "Assassin", "Guardian", "Leader", "Traitor"]
