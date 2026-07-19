"""Getting back into a game after leaving or losing a session."""


class TestSeats:
    def test_lists_seats_without_a_token(self, api, life_room):
        code, _ = life_room
        s = api.call("GET", f"/rooms/{code}/seats")
        assert [x["name"] for x in s["seats"]] == ["host", "p2", "p3"]
        assert s["status"] == "playing"
        assert all(x["vacant"] is False for x in s["seats"])

    def test_a_leaver_shows_as_vacant(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        s = api.call("GET", f"/rooms/{code}/seats")
        assert next(x for x in s["seats"] if x["name"] == "p2")["vacant"] is True

    def test_displays_are_not_seats(self, api, life_room):
        code, _ = life_room
        api.join(code, "tv", display=True)
        s = api.call("GET", f"/rooms/{code}/seats")
        assert "tv" not in [x["name"] for x in s["seats"]]


class TestReclaim:
    def test_leaver_can_come_back(self, api, life_room):
        code, tokens = life_room
        pid = api.pid_of(code, tokens["host"], "p2")
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.me(code, tokens["p2"], expect=403)  # old token is dead
        res = api.call("POST", f"/rooms/{code}/reclaim", body={"pid": pid})
        s = api.me(code, res["playerToken"])
        assert s["me"]["name"] == "p2"
        assert next(p for p in s["players"] if p["name"] == "p2")["left"] is False

    def test_seat_keeps_life_and_commander_damage(self, api, life_room):
        code, tokens = life_room
        host_pid = api.pid_of(code, tokens["host"], "host")
        p2_pid = api.pid_of(code, tokens["host"], "p2")
        api.call("POST", f"/rooms/{code}/life", token=tokens["p2"], body={"delta": -6})
        api.call("POST", f"/rooms/{code}/cmddmg", token=tokens["p2"], body={"attackerPid": host_pid, "delta": 4})
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        res = api.call("POST", f"/rooms/{code}/reclaim", body={"pid": p2_pid})
        me = api.me(code, res["playerToken"])["me"]
        assert me["life"] == 10  # 20 - 6 - 4
        assert me["cmdDamage"] == {str(host_pid): 4}

    def test_treachery_identity_comes_back_with_the_seat(self, api, treachery_room):
        code, tokens = treachery_room
        pid = api.pid_of(code, tokens["p2"], "p2")
        card = api.me(code, tokens["p2"])["me"]["card"]["name"]
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        res = api.call("POST", f"/rooms/{code}/reclaim", body={"pid": pid})
        assert api.me(code, res["playerToken"])["me"]["card"]["name"] == card

    def test_active_seat_needs_force(self, api, life_room):
        """A live session isn't stolen by accident — but a lost session can be recovered."""
        code, tokens = life_room
        pid = api.pid_of(code, tokens["host"], "p2")
        api.call("POST", f"/rooms/{code}/reclaim", body={"pid": pid}, expect=409)
        res = api.call("POST", f"/rooms/{code}/reclaim", body={"pid": pid, "force": True})
        assert api.me(code, res["playerToken"])["me"]["name"] == "p2"
        api.me(code, tokens["p2"], expect=403)  # the old device is logged out

    def test_cannot_reclaim_after_the_game_ends(self, api, life_room):
        code, tokens = life_room
        pid = api.pid_of(code, tokens["host"], "p2")
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        api.call("POST", f"/rooms/{code}/reclaim", body={"pid": pid}, expect=409)

    def test_unknown_seat_404(self, api, life_room):
        code, _ = life_room
        api.call("POST", f"/rooms/{code}/reclaim", body={"pid": 999999}, expect=404)

    def test_rejoin_is_logged(self, api, life_room):
        code, tokens = life_room
        pid = api.pid_of(code, tokens["host"], "p2")
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/reclaim", body={"pid": pid})
        log = [e["text"] for e in api.me(code, tokens["host"])["log"]]
        assert any("p2 rejoined" in x for x in log)

    def test_holding_a_seat_does_not_stop_the_game_ending(self, api, life_room):
        """Leavers are still out — last player standing wins as before."""
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p3"])
        assert api.me(code, tokens["host"])["room"]["status"] == "ended"

    def test_reopen_releases_held_seats(self, api, life_room):
        code, tokens = life_room
        api.call("POST", f"/rooms/{code}/leave", token=tokens["p2"])
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tokens["host"])
        s = api.call("GET", f"/rooms/{code}/seats")
        assert "p2" not in [x["name"] for x in s["seats"]]
