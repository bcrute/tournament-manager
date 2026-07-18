"""Switching a device between player and table display from inside the room."""


class TestBecomeDisplay:
    def test_player_becomes_display(self, api):
        r = api.create()
        t2 = api.join(r["code"], "tv")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/display", token=t2, body={"display": True})
        s = api.me(r["code"], t2)
        assert s["me"]["isDisplay"] is True
        assert s["room"]["displays"] == 1
        assert "tv" not in [p["name"] for p in s["players"]]  # gives up the seat

    def test_display_can_take_a_seat_again(self, api):
        r = api.create()
        t2 = api.join(r["code"], "tv")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/display", token=t2, body={"display": True})
        api.call("POST", f"/rooms/{r['code']}/display", token=t2, body={"display": False})
        s = api.me(r["code"], t2)
        assert s["me"]["isDisplay"] is False
        assert "tv" in [p["name"] for p in s["players"]]

    def test_switching_mid_game_drops_game_state(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -5})
        api.call("POST", f"/rooms/{code}/display", token=tokens["p2"], body={"display": True})
        s = api.me(code, tokens["p2"])
        assert s["me"]["isDisplay"] is True and s["me"]["life"] is None
        assert "p2" not in [p["name"] for p in s["players"]]

    def test_cannot_take_a_seat_mid_game(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        api.call("POST", f"/rooms/{code}/display", token=d, body={"display": False}, expect=409)

    def test_host_role_passes_on_when_host_becomes_display(self, api):
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        t2 = api.join(code, "p2")["playerToken"]
        api.call("POST", f"/rooms/{code}/display", token=t, body={"display": True})
        assert api.me(code, t2)["me"]["isHost"] is True
        assert api.me(code, t)["me"]["isDisplay"] is True

    def test_repeat_call_is_a_noop(self, api):
        r = api.create()
        t2 = api.join(r["code"], "tv")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/display", token=t2, body={"display": True})
        api.call("POST", f"/rooms/{r['code']}/display", token=t2, body={"display": True})

    def test_switch_is_logged(self, api):
        r = api.create()
        t2 = api.join(r["code"], "tv")["playerToken"]
        api.call("POST", f"/rooms/{r['code']}/display", token=t2, body={"display": True})
        log = [e["text"] for e in api.me(r["code"], t2)["log"]]
        assert any("is now the table display" in x for x in log)

    def test_display_does_not_get_dealt_in(self, api):
        r = api.create("host", "treachery")
        code, t = r["code"], r["playerToken"]
        toks = {n: api.join(code, n)["playerToken"] for n in ("p2", "p3", "p4", "tv")}
        api.call("POST", f"/rooms/{code}/display", token=toks["tv"], body={"display": True})
        api.start(code, t)
        assert api.me(code, toks["tv"])["me"]["card"] is None
        assert len(api.me(code, t)["players"]) == 4

    def test_left_player_cannot_become_display(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/display", token=tokens["p2"], body={"display": True}, expect=403)
