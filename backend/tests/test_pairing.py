"""Pod sizing, pairing and seating."""

import pytest

from app.pairing import Entrant, pair_round, pod_sizes, seat_pods


def ids(pods):
    return [p.seats for p in pods]


def flat(pods):
    return [pid for p in pods for pid in p.seats]


class TestPodSizes:
    def test_exact_multiples(self):
        assert pod_sizes(8, 4) == [4, 4]
        assert pod_sizes(12, 4) == [4, 4, 4]

    def test_remainder_of_three_is_its_own_pod(self):
        assert sorted(pod_sizes(11, 4)) == [3, 4, 4]

    def test_never_seats_one_player_alone(self):
        """A remainder of 1 must be absorbed, not left as a pod of one."""
        for n in range(6, 40):
            sizes = pod_sizes(n, 4)
            assert min(sizes) >= 3, f"{n} players produced {sizes}"

    def test_remainder_of_two_is_absorbed(self):
        assert sorted(pod_sizes(10, 4)) == [5, 5]
        assert sum(pod_sizes(10, 4)) == 10

    def test_every_player_is_seated(self):
        for n in range(1, 60):
            assert sum(pod_sizes(n, 4)) == n

    def test_small_tables_stay_whole(self):
        assert pod_sizes(3) == [3]
        assert pod_sizes(4) == [4]
        assert pod_sizes(5) == [5]

    def test_below_a_pod_is_left_to_the_caller(self):
        assert pod_sizes(2) == [2]
        assert pod_sizes(0) == []

    def test_preferred_size_is_respected(self):
        assert pod_sizes(9, 3) == [3, 3, 3]
        assert sorted(pod_sizes(10, 5)) == [5, 5]


class TestPairing:
    def test_everyone_gets_a_seat_exactly_once(self):
        entrants = [Entrant(i) for i in range(1, 12)]
        pods = pair_round(entrants, seed=1)
        seated = flat(pods)
        assert sorted(seated) == list(range(1, 12))

    def test_deterministic_for_a_seed(self):
        entrants = [Entrant(i, points=i % 4) for i in range(1, 13)]
        assert ids(pair_round(entrants, seed=42)) == ids(pair_round(entrants, seed=42))

    def test_reroll_changes_the_pairing(self):
        entrants = [Entrant(i, points=i % 3) for i in range(1, 17)]
        first = ids(pair_round(entrants, seed=1))
        second = ids(pair_round(entrants, seed=2))
        assert first != second

    def test_avoids_rematches_when_it_can(self):
        """Two groups of four who have already played should not be re-paired
        identically when a repeat-free arrangement exists."""
        a, b, c, d = 1, 2, 3, 4
        e, f, g, h = 5, 6, 7, 8
        entrants = [
            Entrant(a, met=(b, c, d)), Entrant(b, met=(a, c, d)),
            Entrant(c, met=(a, b, d)), Entrant(d, met=(a, b, c)),
            Entrant(e, met=(f, g, h)), Entrant(f, met=(e, g, h)),
            Entrant(g, met=(e, f, h)), Entrant(h, met=(e, f, g)),
        ]
        pods = pair_round(entrants, seed=3)
        for pod in pods:
            first_group = sum(1 for pid in pod.seats if pid in (a, b, c, d))
            assert first_group != 4, "re-created an identical pod"

    def test_groups_by_standing(self):
        """With no shared history, the top players should tend to land together."""
        entrants = [Entrant(i, points=9) for i in range(1, 5)] + [
            Entrant(i, points=0) for i in range(5, 9)
        ]
        pods = pair_round(entrants, seed=5)
        for pod in pods:
            points = {1: 9, 2: 9, 3: 9, 4: 9}.get(pod.seats[0], 0)
            same = all(({1, 2, 3, 4}.__contains__(p)) == (points == 9) for p in pod.seats)
            assert same, f"mixed standings in {pod.seats}"

    def test_never_fails_when_repeats_are_unavoidable(self):
        """Everyone has met everyone — the pairer still returns a full pairing."""
        everyone = list(range(1, 9))
        entrants = [Entrant(i, met=tuple(x for x in everyone if x != i)) for i in everyone]
        pods = pair_round(entrants, seed=7)
        assert sorted(flat(pods)) == everyone

    def test_handles_an_empty_field(self):
        assert pair_round([]) == []

    def test_handles_a_single_pod(self):
        pods = pair_round([Entrant(i) for i in range(1, 5)], seed=1)
        assert len(pods) == 1 and len(pods[0].seats) == 4

    def test_large_field(self):
        entrants = [Entrant(i, points=i % 7) for i in range(1, 129)]
        pods = pair_round(entrants, seed=11)
        assert sorted(flat(pods)) == list(range(1, 129))
        assert all(3 <= p.size <= 5 for p in pods)


class TestSeating:
    def test_random_seating_keeps_the_same_players(self):
        from app.pairing import Pod

        pods = [Pod(seats=[1, 2, 3, 4])]
        seated = seat_pods(pods, [Entrant(i) for i in range(1, 5)], "random", seed=2)
        assert sorted(seated[0].seats) == [1, 2, 3, 4]

    def test_by_standings_seats_the_leader_first(self):
        from app.pairing import Pod

        entrants = [Entrant(1, 0), Entrant(2, 9), Entrant(3, 3), Entrant(4, 6)]
        seated = seat_pods([Pod(seats=[1, 2, 3, 4])], entrants, "by_standings", seed=1)
        assert seated[0].seats == [2, 4, 3, 1]

    def test_manual_leaves_order_untouched(self):
        from app.pairing import Pod

        seated = seat_pods([Pod(seats=[3, 1, 2])], [Entrant(i) for i in (1, 2, 3)], "manual")
        assert seated[0].seats == [3, 1, 2]

    def test_seating_is_deterministic(self):
        from app.pairing import Pod

        entrants = [Entrant(i) for i in range(1, 5)]
        a = seat_pods([Pod(seats=[1, 2, 3, 4])], entrants, "random", seed=4)
        b = seat_pods([Pod(seats=[1, 2, 3, 4])], entrants, "random", seed=4)
        assert a[0].seats == b[0].seats

    def test_seating_stream_differs_from_pairing(self):
        """Same seed shouldn't make seating a mirror of pairing order."""
        from app.pairing import Pod

        entrants = [Entrant(i) for i in range(1, 9)]
        pods = pair_round(entrants, seed=1)
        seated = seat_pods(pods, entrants, "random", seed=1)
        assert any(p.seats != s.seats for p, s in zip(pods, seated))
