"""Treachery mode: dealing, tiers, visibility, unveiling, reveal rules."""

from app.table import distribution


def roles_of(api, code, tokens):
    out = {}
    for name, tk in tokens.items():
        me = api.me(code, tk)["me"]
        out[name] = me["card"]
    return out


class TestDeal:
    def test_five_player_distribution(self, api, treachery_room):
        code, tokens = treachery_room
        roles = sorted(c["role"] for c in roles_of(api, code, tokens).values())
        assert roles == ["Assassin", "Assassin", "Guardian", "Leader", "Traitor"]

    def test_everyone_gets_same_rarity_tier(self, api, treachery_room):
        code, tokens = treachery_room
        tiers = {c["rarity"] for c in roles_of(api, code, tokens).values()}
        assert len(tiers) == 1
        assert tiers <= {"U", "R", "M"}  # S can never fill a table

    def test_all_cards_distinct(self, api, treachery_room):
        code, tokens = treachery_room
        ids = [c["id"] for c in roles_of(api, code, tokens).values()]
        assert len(ids) == len(set(ids))

    def test_leader_goes_first_and_starts_revealed(self, api, treachery_room):
        code, tokens = treachery_room
        cards = roles_of(api, code, tokens)
        leader = next(n for n, c in cards.items() if c["role"] == "Leader")
        s = api.me(code, tokens[leader])
        assert s["room"]["firstPlayer"] == leader
        assert s["me"]["revealed"] is True

    def test_non_leaders_start_hidden(self, api, treachery_room):
        code, tokens = treachery_room
        cards = roles_of(api, code, tokens)
        leader = next(n for n, c in cards.items() if c["role"] == "Leader")
        for name in tokens:
            if name == leader:
                continue
            assert api.me(code, tokens[name])["me"]["revealed"] is False

    def test_deal_tier_logged(self, api, treachery_room):
        code, tokens = treachery_room
        log = api.me(code, tokens["host"])["log"]
        assert any("tier" in e["text"] for e in log)

    def test_life_set_in_treachery_too(self, api, treachery_room):
        code, tokens = treachery_room
        s = api.me(code, tokens["host"])
        assert all(p["life"] == 40 for p in s["players"])


class TestVisibility:
    def test_own_card_always_visible_others_hidden(self, api, treachery_room):
        code, tokens = treachery_room
        cards = roles_of(api, code, tokens)
        leader = next(n for n, c in cards.items() if c["role"] == "Leader")
        viewer = next(n for n in tokens if n != leader)
        s = api.me(code, tokens[viewer])
        assert s["me"]["card"] is not None
        for p in s["players"]:
            if p["isMe"] or p["name"] == leader:
                assert p["revealed"] or p["isMe"]
            else:
                assert p["card"] is None  # hidden identities must not leak

    def test_unveil_makes_card_public(self, api, treachery_room):
        code, tokens = treachery_room
        cards = roles_of(api, code, tokens)
        who = next(n for n, c in cards.items() if c["role"] != "Leader")
        api.call("POST", f"/rooms/{code}/unveil", token=tokens[who])
        other = next(n for n in tokens if n != who)
        s = api.me(code, tokens[other])
        p = next(p for p in s["players"] if p["name"] == who)
        assert p["card"] is not None and p["revealed"] is True

    def test_end_reveals_all(self, api, treachery_room):
        code, tokens = treachery_room
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        s = api.me(code, tokens["p2"])
        assert all(p["card"] is not None for p in s["players"])

    def test_end_logs_final_identities(self, api, treachery_room):
        """The reveal must survive the auto-return to the lobby via the log."""
        code, tokens = treachery_room
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tokens["host"])
        log = [e["text"] for e in api.me(code, tokens["p2"])["log"]]
        finals = [t for t in log if t.startswith("final identity:")]
        assert len(finals) == 5
        for name in tokens:
            assert any(name in t for t in finals)

    def test_display_sees_only_public_cards(self, api, treachery_room):
        code, tokens = treachery_room
        d = api.join(code, "tv", display=True)["playerToken"]
        s = api.me(code, d)
        hidden = [p for p in s["players"] if not p["revealed"]]
        assert hidden and all(p["card"] is None for p in hidden)


class TestRevealRules:
    def test_unveil_requires_playing(self, api):
        r = api.create("host", "treachery")
        api.call("POST", f"/rooms/{r['code']}/unveil", token=r["playerToken"], expect=409)

    def test_eliminate_reveals_identity(self, api, treachery_room):
        """CR 907.13: losing the game reveals your face-down identity."""
        code, tokens = treachery_room
        cards = roles_of(api, code, tokens)
        who = next(n for n, c in cards.items() if c["role"] != "Leader")
        api.call("POST", f"/rooms/{code}/eliminate", token=tokens[who], body={})
        s = api.me(code, tokens["host"])
        p = next(p for p in s["players"] if p["name"] == who)
        assert p["eliminated"] and p["card"] is not None

    def test_midgame_leave_reveals_identity(self, api, treachery_room):
        code, tokens = treachery_room
        cards = roles_of(api, code, tokens)
        who = next(n for n, c in cards.items() if c["role"] != "Leader")
        viewer = next(n for n in tokens if n != who)
        api.call("POST", f"/rooms/{code}/leave", token=tokens[who])
        s = api.me(code, tokens[viewer])
        p = next(p for p in s["players"] if p["name"] == who)
        assert p["left"] and p["card"] is not None

    def test_reopen_clears_identities(self, api, treachery_room):
        code, tokens = treachery_room
        api.call("POST", f"/rooms/{code}/end", token=tokens["host"])
        api.call("POST", f"/rooms/{code}/reopen", token=tokens["host"])
        s = api.me(code, tokens["p2"])
        assert s["me"]["card"] is None and s["me"]["revealed"] is False


class TestTierEligibility:
    def test_every_table_size_has_an_eligible_tier(self):
        """Regression guard: card pool must always cover 4-8 player tables in one tier."""
        import json
        from app.table import CARDS_PATH

        cards = json.loads(CARDS_PATH.read_text())["cards"]
        by = {}
        for c in cards:
            by.setdefault(c["types"]["subtype"], {}).setdefault(c["rarity"], 0)
            by[c["types"]["subtype"]][c["rarity"]] += 1
        for n in range(4, 9):
            ldr, trt, ass, gdn = distribution(n)
            need = {"Leader": ldr, "Traitor": trt, "Assassin": ass, "Guardian": gdn}
            eligible = [
                r for r in ("U", "R", "M", "S")
                if all(by.get(role, {}).get(r, 0) >= cnt for role, cnt in need.items())
            ]
            assert eligible, f"no single tier can serve a {n}-player table"


class TestArtistCredit:
    def test_cards_carry_their_artist(self, api, treachery_room):
        """The identity artwork belongs to individual illustrators, so the
        credit has to reach the client that renders it."""
        code, tokens = treachery_room
        card = api.me(code, tokens["host"])["me"]["card"]
        assert card["artist"]

    def test_every_card_in_the_set_has_an_artist(self):
        from app.table import _cards_by_id

        missing = [c["name"] for c in _cards_by_id.values() if not c.get("artist")]
        assert missing == []


class TestRulings:
    def test_cards_carry_their_rulings(self, api, treachery_room):
        """Rulings ship with the card so players can settle questions at the
        table without leaving the app."""
        code, tokens = treachery_room
        card = api.me(code, tokens["host"])["me"]["card"]
        assert isinstance(card["rulings"], list)

    def test_the_whole_set_has_rulings_available(self):
        from app.table import _cards_by_id

        with_rulings = [c for c in _cards_by_id.values() if c.get("rulings")]
        assert len(with_rulings) == len(_cards_by_id)
