"""Seat rearranging from the table display."""


def names(api, code, token):
    return [p["name"] for p in api.me(code, token)["players"]]


def pids(api, code, token):
    return {p["name"]: p["pid"] for p in api.me(code, token)["players"]}


class TestSeatOrder:
    def test_display_reorders_seats(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        p = pids(api, code, d)
        api.call("POST", f"/rooms/{code}/order", token=d, body={"pids": [p["p3"], p["host"], p["p2"]]})
        assert names(api, code, d) == ["p3", "host", "p2"]

    def test_order_is_shared_with_every_device(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        p = pids(api, code, d)
        api.call("POST", f"/rooms/{code}/order", token=d, body={"pids": [p["p2"], p["p3"], p["host"]]})
        assert names(api, code, tokens["p3"]) == ["p2", "p3", "host"]

    def test_host_may_also_reorder(self, api, life_room):
        code, tokens = life_room
        p = pids(api, code, tokens["host"])
        api.call("POST", f"/rooms/{code}/order", token=tokens["host"], body={"pids": [p["p3"], p["p2"], p["host"]]})
        assert names(api, code, tokens["host"]) == ["p3", "p2", "host"]

    def test_regular_player_cannot_reorder(self, api, life_room):
        code, tokens = life_room
        p = pids(api, code, tokens["p2"])
        api.call(
            "POST", f"/rooms/{code}/order", token=tokens["p2"],
            body={"pids": [p["p3"], p["p2"], p["host"]]}, expect=403,
        )

    def test_order_survives_a_new_game(self, api, life_room):
        code, tokens = life_room
        p = pids(api, code, tokens["host"])
        api.call("POST", f"/rooms/{code}/order", token=tokens["host"], body={"pids": [p["p3"], p["host"], p["p2"]]})
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tokens["host"])
        assert names(api, code, tokens["host"]) == ["p3", "host", "p2"]

    def test_latecomer_sits_at_the_end(self, api):
        r = api.create("host", "life")
        code, t = r["code"], r["playerToken"]
        api.join(code, "p2")
        p = pids(api, code, t)
        api.call("POST", f"/rooms/{code}/order", token=t, body={"pids": [p["p2"], p["host"]]})
        api.join(code, "late")
        assert names(api, code, t) == ["p2", "host", "late"]

    def test_unknown_pids_are_ignored(self, api, life_room):
        code, tokens = life_room
        p = pids(api, code, tokens["host"])
        api.call(
            "POST", f"/rooms/{code}/order", token=tokens["host"],
            body={"pids": [999999, p["p3"], p["host"], p["p2"]]},
        )
        assert names(api, code, tokens["host"]) == ["p3", "host", "p2"]

    def test_display_is_not_seated(self, api, life_room):
        code, tokens = life_room
        d = api.join(code, "tv", display=True)["playerToken"]
        p = pids(api, code, d)
        api.call("POST", f"/rooms/{code}/order", token=d, body={"pids": list(p.values())})
        assert "tv" not in names(api, code, d)
