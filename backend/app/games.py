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

    #: room modes this game can run. The room is what tracks live table state;
    #: a game with no room support simply has none and is scored by hand.
    modes: tuple[str, ...] = ()

    #: time-called policies offered for this game, first is the default. Only
    #: `draw_all` is universal; resource ranking only makes sense where the
    #: resource is comparable between players.
    time_called_policies: tuple[str, ...] = ("draw_all",)

    #: label for the optional publisher-account email an organizer may need to
    #: collect for sanctioned play. None means the game has no such concept.
    sanctioning_account: str | None = None

    #: free-form notes surfaced in the organizer UI, e.g. rules citations.
    notes: dict = field(default_factory=dict)


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
    modes=("life", "treachery"),
    # draw_all first: MTR 2.4 makes a match that reaches time a draw. The others
    # are house rules and are labelled as such in the UI.
    time_called_policies=("draw_all", "draw_survivors", "highest_life", "organizer_decides"),
    sanctioning_account="Wizards account email",
    notes={"timeCalled": "MTR 2.4 — a match that goes to time is a draw."},
)


_PROFILES: dict[str, GameProfile] = {p.key: p for p in (MTG,)}

DEFAULT_GAME = "mtg"


def profile_for(key: str | None) -> GameProfile:
    """Resolve a profile, falling back to the default rather than raising —
    a tournament row written before profiles existed has no game recorded."""
    return _PROFILES.get(key or DEFAULT_GAME, MTG)


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
        }
        for p in _PROFILES.values()
    ]
