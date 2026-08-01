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


class TestRoomOpenedByADisplay:
    """A spare tablet sets the table up: it opens the room and shows the code,
    and the players scan their way in. The display holds no seat, so the host's
    controls have to land on somebody who does."""

    def test_the_creating_display_takes_no_seat(self, api):
        r = api.create("tv", display=True)
        s = api.me(r["code"], r["playerToken"])
        assert s["me"]["isDisplay"] is True
        assert s["me"]["isHost"] is False
        assert s["players"] == []
        assert s["room"]["displays"] == 1

    def test_the_first_player_to_join_becomes_host(self, api):
        r = api.create("tv", display=True)
        t2 = api.join(r["code"], "ada")["playerToken"]
        t3 = api.join(r["code"], "bram")["playerToken"]
        assert api.me(r["code"], t2)["me"]["isHost"] is True
        assert api.me(r["code"], t3)["me"]["isHost"] is False

    def test_that_host_can_actually_start_the_game(self, api):
        # the whole point of handing the role over: without it the room opened
        # by a display could never begin
        r = api.create("tv", display=True)
        t2 = api.join(r["code"], "ada")["playerToken"]
        api.join(r["code"], "bram")
        api.start(r["code"], t2)
        assert api.me(r["code"], t2)["room"]["status"] == "playing"

    def test_a_normal_room_still_keeps_its_creator_as_host(self, api):
        r = api.create("ada")
        t2 = api.join(r["code"], "bram")["playerToken"]
        assert api.me(r["code"], r["playerToken"])["me"]["isHost"] is True
        assert api.me(r["code"], t2)["me"]["isHost"] is False

    def test_opening_as_a_display_is_logged(self, api):
        r = api.create("tv", display=True)
        log = [e["text"] for e in api.me(r["code"], r["playerToken"])["log"]]
        assert any("a table display opened the room" in x for x in log)

    def test_the_display_can_take_a_seat_from_the_lobby(self, api):
        # it opened the room, but nothing stops it joining the game after all
        r = api.create("tv", display=True)
        api.call("POST", f"/rooms/{r['code']}/display", token=r["playerToken"],
                 body={"display": False})
        s = api.me(r["code"], r["playerToken"])
        assert s["me"]["isDisplay"] is False
        assert "tv" in [p["name"] for p in s["players"]]


class TestAScorekeeperCanRearrangeToo:
    """`/order` was the one table-wide power that excluded a tracker.

    Everything else a player keeping score can do — adjust anyone's life,
    record commander damage, eliminate them, set "can't lose" — already checks
    `is_display or is_tracker`. Only seat order asked for `is_display or
    is_host`, so a non-host scorekeeper dragged a seat, watched it snap back,
    and got a 403 nobody surfaced.
    """

    def order_of(self, api, code, token):
        return [p["name"] for p in api.me(code, token)["players"]]

    def test_a_non_host_keeping_score_may_reorder(self, api, life_room):
        code, tok = life_room
        api.call("POST", f"/rooms/{code}/tracker", token=tok["p2"], body={"tracking": True})
        pids = [p["pid"] for p in api.me(code, tok["p2"])["players"]]
        api.call(
            "POST", f"/rooms/{code}/order", token=tok["p2"],
            body={"pids": list(reversed(pids))},
        )
        assert [p["pid"] for p in api.me(code, tok["host"])["players"]] == list(reversed(pids))

    def test_an_ordinary_player_still_may_not(self, api, life_room):
        """The rule is about who is keeping the table, not about being seated."""
        code, tok = life_room
        pids = [p["pid"] for p in api.me(code, tok["p3"])["players"]]
        api.call(
            "POST", f"/rooms/{code}/order", token=tok["p3"],
            body={"pids": list(reversed(pids))}, expect=403,
        )

    def test_the_host_still_may(self, api, life_room):
        code, tok = life_room
        pids = [p["pid"] for p in api.me(code, tok["host"])["players"]]
        api.call(
            "POST", f"/rooms/{code}/order", token=tok["host"],
            body={"pids": list(reversed(pids))},
        )
        assert [p["pid"] for p in api.me(code, tok["host"])["players"]] == list(reversed(pids))
