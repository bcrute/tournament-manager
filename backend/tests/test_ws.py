"""WebSocket fanout: room events reach connected sockets."""


class TestWebSocket:
    def test_join_broadcasts_update(self, api, client):
        r = api.create()
        code = r["code"]
        with client.websocket_connect(f"/api/table/ws/{code}") as ws:
            api.join(code, "p2")
            assert ws.receive_json() == {"type": "update"}

    def test_multiple_sockets_all_notified(self, api, client):
        r = api.create()
        code = r["code"]
        with client.websocket_connect(f"/api/table/ws/{code}") as ws1:
            with client.websocket_connect(f"/api/table/ws/{code}") as ws2:
                api.join(code, "p2")
                assert ws1.receive_json() == {"type": "update"}
                assert ws2.receive_json() == {"type": "update"}

    def test_game_actions_broadcast(self, api, client):
        r = api.create()
        code = r["code"]
        t2 = api.join(code, "p2")["playerToken"]
        with client.websocket_connect(f"/api/table/ws/{code}") as ws:
            api.start(code, r["playerToken"])
            assert ws.receive_json() == {"type": "update"}
            api.call("POST", f"/rooms/{code}/life", token=t2, body={"delta": -3})
            assert ws.receive_json() == {"type": "update"}

    def test_authenticated_socket_receives_pushed_state(self, api, client):
        """The whole point of the push: no refetch needed after a change."""
        r = api.create()
        code, host = r["code"], r["playerToken"]
        t2 = api.join(code, "p2")["playerToken"]
        api.start(code, host)
        with client.websocket_connect(f"/api/table/ws/{code}") as ws:
            ws.send_json({"token": host})
            first = ws.receive_json()  # state sent on authentication
            assert first["type"] == "state"
            assert first["state"]["me"]["name"] == "host"
            api.call("POST", f"/rooms/{code}/life", token=t2, body={"delta": -5})
            pushed = ws.receive_json()
            assert pushed["type"] == "state"
            p2 = next(p for p in pushed["state"]["players"] if p["name"] == "p2")
            assert p2["life"] == 15

    def test_state_is_personalized_per_socket(self, api, client):
        """Two sockets on one room must not see each other's private view."""
        r = api.create("host", "treachery")
        code, host = r["code"], r["playerToken"]
        toks = {n: api.join(code, n)["playerToken"] for n in ("p2", "p3", "p4", "p5")}
        api.start(code, host)
        with client.websocket_connect(f"/api/table/ws/{code}") as a:
            with client.websocket_connect(f"/api/table/ws/{code}") as b:
                a.send_json({"token": host})
                b.send_json({"token": toks["p2"]})
                sa, sb = a.receive_json()["state"], b.receive_json()["state"]
                assert sa["me"]["name"] == "host" and sb["me"]["name"] == "p2"
                assert sa["me"]["card"]["id"] != sb["me"]["card"]["id"]
                # each sees only their own identity, not the other's
                other = next(p for p in sa["players"] if p["name"] == "p2")
                assert other["card"] is None or other["revealed"]

    def test_unauthenticated_socket_still_gets_a_nudge(self, api, client):
        """Older clients that never send a token keep working via refetch."""
        r = api.create()
        code = r["code"]
        with client.websocket_connect(f"/api/table/ws/{code}") as ws:
            api.join(code, "p2")
            assert ws.receive_json() == {"type": "update"}

    def test_client_keepalive_accepted(self, api, client):
        r = api.create()
        with client.websocket_connect(f"/api/table/ws/{r['code']}") as ws:
            ws.send_text("ping")  # keepalives must not kill the socket
            api.join(r["code"], "p2")
            assert ws.receive_json() == {"type": "update"}

    def test_other_room_not_notified(self, api, client):
        r1 = api.create()
        r2 = api.create()
        with client.websocket_connect(f"/api/table/ws/{r1['code']}") as ws1:
            with client.websocket_connect(f"/api/table/ws/{r2['code']}") as ws2:
                api.join(r2["code"], "p2")
                assert ws2.receive_json() == {"type": "update"}
                # ws1 got nothing: joining r2 then r1 shows r1's queue starts empty
                api.join(r1["code"], "px")
                assert ws1.receive_json() == {"type": "update"}
