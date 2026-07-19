

class TestTrackerMode:
    """One player's phone keeping score for the table, without giving up their
    seat — the case a group with no spare tablet actually has."""

    def _room(self, client, names=("alice", "bob")):
        r = client.post("/api/table/rooms", json={"name": names[0], "mode": "life"}).json()
        toks = {names[0]: r["playerToken"]}
        for n in names[1:]:
            toks[n] = client.post(f"/api/table/rooms/{r['code']}/join",
                                  json={"name": n, "display": False}).json()["playerToken"]
        client.post(f"/api/table/rooms/{r['code']}/start",
                    headers={"X-Player-Token": toks[names[0]]})
        return r["code"], toks

    def _state(self, client, code, token):
        return client.get(f"/api/table/rooms/{code}/me",
                          headers={"X-Player-Token": token}).json()

    def test_a_player_cannot_adjust_others_by_default(self, client):
        code, toks = self._room(client)
        me = self._state(client, code, toks["alice"])
        other = next(p for p in me["players"] if p["name"] == "bob")
        r = client.post(f"/api/table/rooms/{code}/life",
                        headers={"X-Player-Token": toks["alice"]},
                        json={"delta": -3, "playerPid": other["pid"]})
        assert r.status_code == 403

    def test_tracking_grants_it_without_touching_the_seat(self, client):
        code, toks = self._room(client)
        before = self._state(client, code, toks["alice"])["me"]
        assert client.post(f"/api/table/rooms/{code}/tracker",
                           headers={"X-Player-Token": toks["alice"]},
                           json={"tracking": True}).status_code == 200
        after = self._state(client, code, toks["alice"])["me"]
        # the seat is untouched: same life, still a player, still host
        assert after["isTracker"] is True
        assert after["life"] == before["life"]
        assert after["isDisplay"] is False
        assert after["isHost"] == before["isHost"]

        other = next(p for p in self._state(client, code, toks["alice"])["players"]
                     if p["name"] == "bob")
        assert client.post(f"/api/table/rooms/{code}/life",
                           headers={"X-Player-Token": toks["alice"]},
                           json={"delta": -3, "playerPid": other["pid"]}).status_code == 200

    def test_it_is_reversible_mid_game(self, client):
        """The display flag can only be undone from the lobby. Handing score
        keeping back mid-game is the whole point of this being separate."""
        code, toks = self._room(client)
        client.post(f"/api/table/rooms/{code}/tracker",
                    headers={"X-Player-Token": toks["alice"]}, json={"tracking": True})
        r = client.post(f"/api/table/rooms/{code}/tracker",
                        headers={"X-Player-Token": toks["alice"]}, json={"tracking": False})
        assert r.status_code == 200
        assert self._state(client, code, toks["alice"])["me"]["isTracker"] is False

    def test_the_log_names_who_changed_someone_elses_total(self, client):
        """'by the table display' is fine for a shared screen anyone can reach.
        When a person is keeping score, the table should see whose phone it was."""
        code, toks = self._room(client)
        client.post(f"/api/table/rooms/{code}/tracker",
                    headers={"X-Player-Token": toks["alice"]}, json={"tracking": True})
        other = next(p for p in self._state(client, code, toks["alice"])["players"]
                     if p["name"] == "bob")
        client.post(f"/api/table/rooms/{code}/life",
                    headers={"X-Player-Token": toks["alice"]},
                    json={"delta": -3, "playerPid": other["pid"]})
        log = " ".join(e["text"] for e in self._state(client, code, toks["alice"])["log"])
        assert "by alice" in log

    def test_adjusting_your_own_total_is_not_attributed(self, client):
        code, toks = self._room(client)
        client.post(f"/api/table/rooms/{code}/life",
                    headers={"X-Player-Token": toks["alice"]}, json={"delta": -1})
        log = " ".join(e["text"] for e in self._state(client, code, toks["alice"])["log"])
        assert "by alice" not in log

    def test_becoming_tracker_is_announced_to_the_table(self, client):
        code, toks = self._room(client)
        client.post(f"/api/table/rooms/{code}/tracker",
                    headers={"X-Player-Token": toks["alice"]}, json={"tracking": True})
        log = " ".join(e["text"] for e in self._state(client, code, toks["bob"])["log"])
        assert "keeping score" in log

    def test_a_dedicated_display_cannot_also_be_a_tracker(self, client):
        code, toks = self._room(client)
        client.post(f"/api/table/rooms/{code}/display",
                    headers={"X-Player-Token": toks["bob"]}, json={"display": True})
        r = client.post(f"/api/table/rooms/{code}/tracker",
                        headers={"X-Player-Token": toks["bob"]}, json={"tracking": True})
        assert r.status_code == 409

    def test_more_than_one_player_may_keep_score(self, client):
        """Not restricted to one: two people tracking is harmless, and refusing
        would strand the table if the tracker's phone died."""
        code, toks = self._room(client, ("alice", "bob", "carol"))
        for who in ("alice", "bob"):
            assert client.post(f"/api/table/rooms/{code}/tracker",
                               headers={"X-Player-Token": toks[who]},
                               json={"tracking": True}).status_code == 200
