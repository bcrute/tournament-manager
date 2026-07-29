"""Multiplayer pod pairing.

Pure functions — no database, no clock, no randomness beyond an explicit seed.
Everything here is deterministic given (entrants, history, seed), so an
organizer's re-roll is reproducible and a disputed pairing can be re-derived.

The problem is Swiss adapted to pods: group players of similar standing, avoid
re-pairing people who have already met, and never leave anyone without a table.
Zero repeats is often impossible (an 8-player, 4-round event exhausts the
combinations), so repeats are *costed*, not forbidden. The pairer always returns
a pairing.
"""

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entrant:
    id: int
    points: int = 0
    # ids this entrant has already shared a pod with, one entry per meeting
    met: tuple[int, ...] = ()


@dataclass
class Pod:
    seats: list[int] = field(default_factory=list)  # entrant ids, in seat order

    @property
    def size(self) -> int:
        return len(self.seats)


# Cost weights. Repeats dominate: a pairing that avoids a rematch is better than
# one with a tidier points spread.
REPEAT_COST = 10
SPREAD_COST = 1


def pod_sizes(n: int, preferred: int = 4) -> list[int]:
    """How to split n players into pods.

    Prefers `preferred`, degrades to 3 and 5, and never produces a pod of 1 or 2
    — a remainder gets absorbed into a neighbouring pod instead. Byes are the
    caller's problem and only arise below a single pod's worth of players.

    **Except at 1v1, where a pod of two is the table.** Everything below this
    guard is a multiplayer rule: "no pod smaller than three" is right for
    Commander and nonsense for a duel, and applying it to a duel seated four
    players at one table. A duel is pairs, with an odd player out in a
    one-seat pod the organizer reports as a bye — which is how this app models
    byes anyway (`pod_results.kind = 'bye'`).
    """
    if n <= 0:
        return []
    if preferred <= 2:
        pairs, odd = divmod(n, 2)
        return [2] * pairs + ([1] if odd else [])
    if n < 3:
        return [n]  # too few for a pod at all; caller issues byes
    if n <= 5:
        return [n]

    pods, remainder = divmod(n, preferred)
    if remainder == 0:
        return [preferred] * pods

    sizes = [preferred] * pods
    if remainder >= 3:
        # a legal pod on its own
        sizes.append(remainder)
    else:
        # 1 or 2 left over: grow existing pods rather than seat someone alone
        for i in range(remainder):
            sizes[i % len(sizes)] += 1
    return sorted(sizes, reverse=True)


def bracket_pods(order: list[int], pod_size: int = 2) -> list[Pod]:
    """Single-elimination pods for a field already in bracket order.

    `order` is strongest first — bracket seeds in the first cut round, and the
    previous round's pod order after that. Ordering by the pod a player came
    out of, rather than re-seeding on standings, is what keeps the bracket
    *fixed*: MTR Appendix E has the 1v8 winner meet the 4v5 winner whoever
    actually won, and a re-seeded bracket quietly rewards an upset.

    Any remainder is taken off the top as byes, one pod of one each, because a
    bye is worth most to the seed who earned it. The rest snake across the
    tables — 1 and 8 together, 2 and 7, 3 and 6, 4 and 5 — which for a duel is
    exactly the published bracket and for pods is its natural generalisation.

    A pod of one is a bye and the caller treats it as such: no room, no game.
    Returns [] when there is nobody left to play, i.e. the bracket is decided.
    """
    size = max(2, pod_size)
    if len(order) < 2:
        return []
    if len(order) <= size:
        return [Pod(seats=list(order))]

    byes, rest = order[: len(order) % size], order[len(order) % size :]
    tables: list[list[int]] = [[] for _ in range(len(rest) // size)]
    for i, entrant_id in enumerate(rest):
        row, col = divmod(i, len(tables))
        # serpentine: the strongest table takes the weakest of the next band
        tables[col if row % 2 == 0 else len(tables) - 1 - col].append(entrant_id)
    return [Pod(seats=[b]) for b in byes] + [Pod(seats=t) for t in tables]


def _pod_cost(pod: list[Entrant]) -> float:
    """Lower is better: rematches first, then how far apart the pod's standings are."""
    repeats = 0
    for i, a in enumerate(pod):
        for b in pod[i + 1 :]:
            repeats += a.met.count(b.id) + b.met.count(a.id)
    spread = max((e.points for e in pod), default=0) - min((e.points for e in pod), default=0)
    return repeats * REPEAT_COST + spread * SPREAD_COST


def _total_cost(pods: list[list[Entrant]]) -> float:
    return sum(_pod_cost(p) for p in pods)


def _seed_order(entrants: list[Entrant], rng: random.Random) -> list[Entrant]:
    """Standings order, ties broken randomly so equal players aren't always
    paired in the same direction round after round."""
    shuffled = entrants[:]
    rng.shuffle(shuffled)
    return sorted(shuffled, key=lambda e: -e.points)


def pair_round(
    entrants: list[Entrant],
    preferred_size: int = 4,
    seed: int = 0,
    improve_rounds: int = 400,
) -> list[Pod]:
    """Assign entrants to pods, minimising rematches then standings spread.

    Greedy seeding (strongest first, filling pods in standings order) followed by
    a local search that swaps pairs of players whenever it lowers the cost.
    """
    if not entrants:
        return []
    rng = random.Random(seed)
    sizes = pod_sizes(len(entrants), preferred_size)

    ordered = _seed_order(entrants, rng)
    pods: list[list[Entrant]] = []
    cursor = 0
    for size in sizes:
        pods.append(ordered[cursor : cursor + size])
        cursor += size

    # local search: try swapping members between pods, keep improvements
    flat_positions = [(pi, si) for pi, pod in enumerate(pods) for si in range(len(pod))]
    if len(flat_positions) > 1:
        cost = _total_cost(pods)
        for _ in range(improve_rounds):
            (pa, sa), (pb, sb) = rng.sample(flat_positions, 2)
            if pa == pb:
                continue
            pods[pa][sa], pods[pb][sb] = pods[pb][sb], pods[pa][sa]
            new_cost = _total_cost(pods)
            if new_cost < cost:
                cost = new_cost
            else:
                pods[pa][sa], pods[pb][sb] = pods[pb][sb], pods[pa][sa]  # revert

    return [Pod(seats=[e.id for e in pod]) for pod in pods]


def seat_pods(
    pods: list[Pod],
    entrants: list[Entrant],
    mode: str = "random",
    seed: int = 0,
) -> list[Pod]:
    """Decide turn order within each pod.

    Seat 1 takes the first turn, which is a real advantage in multiplayer, so
    this is a fairness setting rather than cosmetics:
      random       — shuffled (default)
      by_standings — highest points seated first
      manual       — left as-is for the organizer to arrange, which they do
                     through POST /pods/{id}/seats once the round is open
    """
    if mode == "manual":
        return pods
    rng = random.Random(seed + 7919)  # distinct stream from pairing
    points = {e.id: e.points for e in entrants}
    out = []
    for pod in pods:
        seats = pod.seats[:]
        rng.shuffle(seats)  # break standings ties randomly in both modes
        if mode == "by_standings":
            seats.sort(key=lambda pid: -points.get(pid, 0))
        out.append(Pod(seats=seats))
    return out
