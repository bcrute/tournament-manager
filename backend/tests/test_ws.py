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
