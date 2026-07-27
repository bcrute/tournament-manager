"""Game profiles.

The tournament manager is deliberately game-agnostic: entrants, rounds, pods,
seats, placements, standings, timers and judge calls are true of any tabletop
event. What differs between games is a small, enumerable set of facts — how many
players sit at a table, what resource they track and which way it moves, what a
"mode" means, who sanctions the event.

Those facts live here, not scattered through the tournament code. MTG is a
*surface* over the core, not the base of it; adding Lorcana or anything else
should mean adding a profile and, if the game needs live table state, a room
mode — never editing `tournaments.py`.

Nothing here is a rules engine. A profile supplies defaults and vocabulary; it
does not adjudicate games.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameProfile:
    key: str
    name: str
    publisher: str

    #: seats at a table by default. 4 for multiplayer Commander, 2 for a duel.
    default_pod_size: int
    default_round_minutes: int

    #: the resource players track. MTG counts life *down* from 40; a game like
    #: Lorcana counts lore *up* to a target. `resource_goal` is the value that
    #: ends a game, and direction says which side of it wins.
    resource: str
    resource_start: int
    resource_direction: str  # "down" | "up"
    resource_goal: int

    #: formats a *tournament* of this game can be run in, and the only thing
    #: this field governs — `tournaments.py` validates against it and the
    #: create form offers it. A room's own modes are separate (`table.MODES`),
    #: so a format missing here can still be played casually at a table.
    modes: tuple[str, ...] = ()

    #: time-called policies offered for this game, first is the default. Only
    #: `draw_all` is universal; resource ranking only makes sense where the
    #: resource is comparable between players.
    time_called_policies: tuple[str, ...] = ("draw_all",)

    #: label for the optional publisher-account email an organizer may need to
    #: collect for sanctioned play. None means the game has no such concept.
    sanctioning_account: str | None = None

    #: turns played after time is called before the game is decided. The app
    #: cannot detect a turn passing, so this is a counter players advance
    #: themselves — which is what they already do at the table.
    extra_turns_at_time: int = 0

    #: event structures an organizer may pick from, official ones first.
    structures: tuple = ()

    #: free-form notes surfaced in the organizer UI, e.g. rules citations.
    notes: dict = field(default_factory=dict)




@dataclass(frozen=True)
class Bracket:
    """One attendance band: how many Swiss rounds, then what playoff."""

    max_players: int          # inclusive upper bound; a sentinel for the last band
    swiss_rounds: int         # 0 means run single elimination from the start
    cut_to: int               # 0 = no cut; otherwise the top N who advance
    elim_rounds: int = 0      # single-elimination rounds when swiss_rounds is 0


@dataclass(frozen=True)
class EventStructure:
    key: str
    name: str
    #: True only when a published rules document specifies this table. A house
    #: convention must never be presented to an organizer as an official one.
    official: bool
    source: str
    #: smallest field this structure is defined for
    min_players: int
    bands: tuple[Bracket, ...]
    #: seats per table this structure assumes; multiplayer structures differ
    pod_size: int = 2
    notes: str = ""

    def plan(self, players: int) -> dict:
        """Rounds and cut for a given attendance. Never raises — an organizer
        running an odd-sized event still needs an answer."""
        if players < self.min_players:
            return {
                "players": players,
                "swissRounds": 0,
                "cutTo": 0,
                "elimRounds": 0,
                "belowMinimum": True,
                "structure": self.key,
                "official": self.official,
                "source": self.source,
            }
        band = next((b for b in self.bands if players <= b.max_players), self.bands[-1])
        return {
            "players": players,
            "swissRounds": band.swiss_rounds,
            "cutTo": band.cut_to,
            "elimRounds": band.elim_rounds,
            "belowMinimum": False,
            "structure": self.key,
            "official": self.official,
            "source": self.source,
        }


_BIG = 10**9

# --- Magic: the Gathering -------------------------------------------------
# Verbatim from MTR Appendix E (effective 2026-02-27), "All Other Formats"
# column. Required for Premier events; optional elsewhere at the organizer's
# discretion. This table is 1v1 only — the MTR defines no multiplayer
# structure whatsoever.
MTR_PREMIER = EventStructure(
    key="mtr_premier",
    name="MTR Appendix E — Premier (1v1)",
    official=True,
    source="MTG Magic Tournament Rules, Appendix E, effective 2026-02-27",
    min_players=4,
    pod_size=2,
    bands=(
        Bracket(max_players=4, swiss_rounds=0, cut_to=4, elim_rounds=2),
        Bracket(max_players=8, swiss_rounds=0, cut_to=8, elim_rounds=3),
        Bracket(max_players=16, swiss_rounds=5, cut_to=4),
        Bracket(max_players=32, swiss_rounds=5, cut_to=8),
        Bracket(max_players=64, swiss_rounds=6, cut_to=8),
        Bracket(max_players=128, swiss_rounds=7, cut_to=8),
        Bracket(max_players=226, swiss_rounds=8, cut_to=8),
        Bracket(max_players=409, swiss_rounds=9, cut_to=8),
        Bracket(max_players=_BIG, swiss_rounds=10, cut_to=8),
    ),
    notes=(
        "4 and 5–8 player events run single elimination with no Swiss. "
        "Limited events with a booster draft in the playoff use 4 rounds and cut "
        "to Top 8 at 9–16 players instead of 5 rounds to Top 4."
    ),
)

MTR_PREMIER_LIMITED = EventStructure(
    key="mtr_premier_limited",
    name="MTR Appendix E — Premier, Limited with draft playoff (1v1)",
    official=True,
    source="MTG Magic Tournament Rules, Appendix E, effective 2026-02-27",
    min_players=4,
    pod_size=2,
    bands=(
        Bracket(max_players=4, swiss_rounds=0, cut_to=4, elim_rounds=2),
        Bracket(max_players=8, swiss_rounds=0, cut_to=8, elim_rounds=3),
        Bracket(max_players=16, swiss_rounds=4, cut_to=8),
        Bracket(max_players=32, swiss_rounds=5, cut_to=8),
        Bracket(max_players=64, swiss_rounds=6, cut_to=8),
        Bracket(max_players=128, swiss_rounds=7, cut_to=8),
        Bracket(max_players=226, swiss_rounds=8, cut_to=8),
        Bracket(max_players=409, swiss_rounds=9, cut_to=8),
        Bracket(max_players=_BIG, swiss_rounds=10, cut_to=8),
    ),
)

# Multiplayer Commander has NO official tournament structure: the MTR (56pp,
# 2026-02-27) contains no multiplayer section, and mentions "Commander" only as
# a set name in Vintage/Legacy legality lists. These are common community
# conventions and are flagged official=False so the UI can say so plainly.
COMMANDER_PODS = EventStructure(
    key="commander_pods_house",
    name="Commander pods — house convention (unofficial)",
    official=False,
    source="Community convention; no published rules document defines this",
    min_players=4,
    pod_size=4,
    bands=(
        Bracket(max_players=8, swiss_rounds=2, cut_to=0),
        Bracket(max_players=16, swiss_rounds=3, cut_to=4),
        Bracket(max_players=32, swiss_rounds=3, cut_to=4),
        Bracket(max_players=64, swiss_rounds=4, cut_to=4),
        Bracket(max_players=_BIG, swiss_rounds=5, cut_to=4),
    ),
    notes=(
        "Swiss over pods of four, then a single final pod. Wizards publishes no "
        "multiplayer structure, so this is a convention, not a rule."
    ),
)

COMMANDER_NO_CUT = EventStructure(
    key="commander_swiss_only_house",
    name="Commander — Swiss only, no cut (unofficial)",
    official=False,
    source="Community convention; no published rules document defines this",
    min_players=4,
    pod_size=4,
    bands=(
        Bracket(max_players=16, swiss_rounds=3, cut_to=0),
        Bracket(max_players=64, swiss_rounds=4, cut_to=0),
        Bracket(max_players=_BIG, swiss_rounds=5, cut_to=0),
    ),
    notes="Highest points after Swiss wins. Common for casual league nights.",
)

MTG = GameProfile(
    key="mtg",
    name="Magic: The Gathering",
    publisher="Wizards of the Coast",
    default_pod_size=4,
    default_round_minutes=60,
    resource="life",
    resource_start=40,
    resource_direction="down",
    resource_goal=0,
    # Life only. Treachery is a hidden-role variant: it has no standings a
    # Swiss event can rank, and the identities it deals are the one part of the
    # app whose art we host on someone else's goodwill. It stays available for
    # a casual room, which is where it is actually played.
    modes=("life",),
    # draw_all first: MTR 2.4 makes an unfinished game a draw *in Swiss*. In
    # single elimination the same section says highest life wins — so
    # highest_life is the official behaviour for a cut, not a house rule, and
    # only draw_survivors is purely a house convention.
    time_called_policies=("draw_all", "draw_survivors", "highest_life", "organizer_decides"),
    sanctioning_account="Wizards account email",
    # MTR 2.4: the current turn is finished, then five additional turns.
    # (Two-Headed Giant uses three; that would be its own profile.)
    extra_turns_at_time=5,
    structures=(MTR_PREMIER, MTR_PREMIER_LIMITED, COMMANDER_PODS, COMMANDER_NO_CUT),
    notes={
        # verified against the primary document, 2026-02-27 revision
        "timeCalled": (
            "MTR 2.4 — at time, the turn is finished and five additional turns are "
            "played; an incomplete game is then a draw."
        ),
        "singleElimination": (
            "MTR 2.4 — single-elimination matches may not end in a draw: after the "
            "additional turns the highest life total wins."
        ),
        "multiplayer": (
            "The MTR defines no multiplayer tournament structure. Commander pod "
            "structures are community conventions, not rules."
        ),
    },
)


_PROFILES: dict[str, GameProfile] = {p.key: p for p in (MTG,)}

DEFAULT_GAME = "mtg"


def profile_for(key: str | None) -> GameProfile:
    """Resolve a profile, falling back to the default rather than raising —
    a tournament row written before profiles existed has no game recorded."""
    return _PROFILES.get(key or DEFAULT_GAME, MTG)


def structure_for(
    game: str | None, key: str | None, pod_size: int | None = None
) -> EventStructure | None:
    """Resolve a structure, defaulting to one that fits how the event is seated.

    Falling back to the first structure meant a four-to-a-pod Commander event
    was advised from the 1v1 Premier table — "0 Swiss rounds, cut to top 8" for
    eight players, which is right for duels and nonsense for pods. When no
    structure was chosen, prefer one whose seating matches.
    """
    p = profile_for(game)
    if not p.structures:
        return None
    chosen = next((s for s in p.structures if s.key == key), None)
    if chosen:
        return chosen
    if pod_size:
        fits = next((s for s in p.structures if s.pod_size == pod_size), None)
        if fits:
            return fits
    return p.structures[0]


def known_games() -> list[dict]:
    """What the organizer UI offers. One entry today; the shape is the point."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "publisher": p.publisher,
            "defaultPodSize": p.default_pod_size,
            "modes": list(p.modes),
            "resource": p.resource,
            "timeCalledPolicies": list(p.time_called_policies),
            "sanctioningAccount": p.sanctioning_account,
            "extraTurnsAtTime": p.extra_turns_at_time,
            "structures": [
                {"key": s.key, "name": s.name, "official": s.official,
                 "source": s.source, "podSize": s.pod_size, "notes": s.notes}
                for s in p.structures
            ],
            "notes": p.notes,
        }
        for p in _PROFILES.values()
    ]
