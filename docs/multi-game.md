# Multi-game readiness

*Written 2026-07-24. A work plan, not a design doc — each item below is scoped
to be picked up independently.*

## What this project is

A standalone, open-source tournament manager for tabletop games. It is a
portfolio piece: it takes no money, makes no money, and has no commercial tier.
Success is that a shop owner or a league organizer could actually run their
Friday night on it, for whichever game they play, and that the code reads like
someone thought about it.

It is **not** the events platform. Some of the same thinking led to both, but
that is a separate, larger project and nothing here is a slice of it. Where
this repo's docs refer to `events-platform.md` — a file that does not exist
here and never will — the reference is wrong and should be cut (see W0).

The goal of this document: **adding Lorcana, Pokémon, or anything else should
mean writing one profile and its tests, and touching nothing else.** That is
already the stated architecture. It isn't yet true. This is the list of what's
in the way.

---

## What is already right

Worth stating plainly, because the work below is corrective and it would be
easy to read it as "the abstraction failed." It didn't — the seams are in the
right places, and most of the fixes are small.

- **`GameProfile` covers the right facts** — table size, round length, the
  tracked resource and its direction, room modes, time-called policies, the
  sanctioning concept, event structures. Nothing in the list is MTG-shaped.
- **`EventStructure` / `Bracket` carry their own provenance.** `official` plus
  `source`, with the rule that `official=True` requires a published document.
  This is the single best thing in the codebase and every new game inherits it.
- **Settings are already split** — `GENERIC_SETTINGS` versus `defaults_for()`,
  which pulls table and resource facts from the profile.
- **Creation already validates against the profile**: unknown game rejected,
  mode checked against `profile.modes`, `timeCalledPolicy` checked against the
  profile's list, and unknown settings keys dropped rather than stored.
- **`structure_for()` already defends the multiplayer case** — falling back to
  a structure whose `pod_size` matches how the event is seated, instead of
  advising a pod event from the 1v1 table.
- **The pairer is pure** — deterministic given `(entrants, history, seed)`.
- **The organizer UI is already conditional**: `Host.tsx` renders the game
  selector when `games.length > 1`, so a second profile appears in the UI with
  no front-end change at all.

---

## Blockers — bugs reachable today

These are not "multi-game" problems in the abstract. Both are live defects in
shipped code, because MTG's own `MTR_PREMIER` structure is `pod_size=2` and the
create form lets an organizer set players-per-pod to 2 (`Host.tsx:274`,
`min={2}`). Any duel game makes them worse; nothing makes them theoretical.

### B1 — `pod_sizes()` assumes tables of about four

`backend/app/pairing.py:41`. Verified by running it:

```
pod_sizes(n, preferred=2):
  3 -> [3]      4 -> [4]      5 -> [5]
  7 -> [3,2,2]  9 -> [3,2,2,2]  11 -> [3,2,2,2,2]
```

A five-player 1v1 event seats all five players at one table. Every odd
attendance produces a three-player pod in a game that has no three-player
match. Two hardcoded assumptions cause it:

- `if n <= 5: return [n]` — "small fields stay whole" is right for pods of
  four and nonsense for duels.
- `remainder >= 3` → "a legal pod on its own" — true only when `preferred` is
  4 or 5.

**The fix is to make legality a property of the game, not a constant.** A
profile needs to say what table sizes are permissible — most simply
`min_pod_size` / `max_pod_size`, where a duel game is `(2, 2)` and Commander is
`(3, 5)`. `pod_sizes` then splits within those bounds and hands the true
remainder back to the caller as a bye. `test_small_tables_stay_whole` and
`test_remainder_of_three_is_its_own_pod` encode the current behaviour and will
need to become size-aware rather than deleted.

### B2 — byes do not exist end to end

`points_for()` scores `kind == "bye"` (`tournaments.py:799`), `byeScoring` is a
setting, and the schema comment lists `bye` as a result kind (`db.py:160`).
Nothing ever creates one. `pod_sizes` says byes are "the caller's problem"; the
caller, `open_round` (`tournaments.py:753`), pairs the entire field into pods
and creates a room for each. The bye path is configured, scored, documented,
and unreachable.

For pods of four this is nearly invisible — the pairer absorbs remainders. For
any 1v1 game **every odd round needs a bye**, so this is a hard prerequisite for
Pokémon or Lorcana, and it must be paired with B1 rather than after it.

Bye rules that need deciding rather than discovering: who receives it (lowest
standing, never twice, never a dropped entrant), that it needs no room, and
that it closes as complete without an organizer reporting anything — today
`close_round` refuses while any pod is not `complete`.

---

## Leaks — MTG vocabulary in game-independent code

Each is small. Together they are what makes a second profile feel bolted on.

### L1 — the sanctioning account is spelled "Wizards"

`GENERIC_SETTINGS["collectWizardsEmail"]` sits in the dict whose comment says
"Keep this list free of MTG assumptions." It reaches the schema
(`entrants.wizards_email`, `db.py:123`), the API (`wizardsEmail`), the client
(`api.ts:186`), and the 422 text: *"this event reports to Wizards"*.

The profile already has the generic half — `sanctioning_account`, a label like
"Wizards account email", `None` when the game has no such concept. Rename the
setting to `collectSanctioningId`, the column to `sanctioning_id`, and source
every user-facing string from `profile.sanctioning_account`. Needs a migration
(`_ensure_column` plus a copy) and a contract update. Do it before a second
game ships, not after, so there is only one live spelling.

### L2 — `highest_life` ignores `resource_direction`

`resolve_pod_at_time()` (`tournaments.py:908`) reads `players.life` and sorts
descending. The profile already records that Lorcana-shaped games count *up* to
a goal, and the field is simply not consulted — for an up-counting resource,
"highest" happens to be correct, but the policy is named `highest_life` and the
note it writes says "ranked on life". A game whose resource counts down to a
target other than zero would rank backwards.

Rename the policy `highest_resource`, sort by direction, and take the note's
wording from `profile.resource`. Keep `highest_life` accepted as an alias —
it's persisted in existing tournaments' settings JSON.

### L3 — a game with no room still gets a room

`create_tournament` validates mode only `if profile.modes` — correct, since a
hand-scored game has none. But `open_round` unconditionally calls
`_make_room_for_pod` (`tournaments.py:676`), which inserts a room with
`t["mode"]` and `cfg["startingLife"]`. A profile with `modes=()` therefore
produces a life-counter room at every table for a game that has no life.

`games.py` already promises the opposite: *"a game with no room support simply
has none and is scored by hand."* Make that true — when the profile has no
modes, skip room creation and leave the pod to be reported by the organizer.
`resolve_pod_at_time` already handles `not pod["room_code"]`, so the hard part
is only `open_round` and whatever the player view assumes. **This is the item
that makes the first new game cheap**, because it means Lorcana can ship as a
profile with no table support at all.

### L4 — the fan content notice is MTG's, and it is global

`FanContentNotice.tsx` renders the Wizards Fan Content paragraph and the MTG
Treachery credit. Its wording is fixed by Wizards' policy and must not be
paraphrased — which is exactly why it must not appear on a Lorcana event.
Ravensburger and The Pokémon Company have their own community-use terms with
their own required wording.

Attribution belongs to the profile: a list of notices, rendered per game, with
the MTG text unchanged. Whatever a new profile's publisher requires must be
quoted from the primary source or left out — an invented attribution is worse
than none.

### L5 — hardcoded mode labels and placeholders

`Host.tsx:243` maps mode keys to English inline (`"life"` → "Life counter",
`"treachery"` → "Hidden roles", otherwise the raw key), and the event-name
placeholder is "Friday Night Commander". Modes should carry their own display
name in the profile; the placeholder should come from the profile or go
generic.

### L6 — `startingLife` on the wire

Deliberate, and documented as such (`tournaments.py:64`): the room API already
speaks it and renaming a live key buys nothing. **Recorded here so it is a
decision rather than an oversight.** Recommendation: leave it. It is one
already-explained name, versus a migration touching the frozen table surface.
Revisit only if the table layer gains a second resource type.

### L7 — the app's own name

`TREACHERY_DB`, `treachery.db`, `main.py` title `"mtg"`, and the health
endpoint's `"app": "mtg"`. Cosmetic, deployment-visible (`mtg.env`,
`/opt/apps/mtg`, `mtg.skadoosh.dev`), and entangled with the Caddy vhost work
that just landed. **Lowest priority; possibly never.** Listed so nobody
discovers it mid-rename and assumes it was missed.

---

## Missing — what "solid" actually requires

The items above get a second profile in. These are what make the result a
tournament manager someone would choose.

### M1 — matches are best-of-three, and the model has no games

The data model records one result per pod: places, points, a kind. Competitive
Pokémon, Lorcana, and MTG 1v1 all play a **match** of up to three games, and
report `2-0`, `2-1`, or `1-1-1`. That distinction is not cosmetic — game wins
feed the tiebreakers in M2, and "1-1-1" is a drawn match with a game record,
which the current schema cannot express.

`pods.game_no` exists and is set to 0. This is the largest modelling decision
in the document and should be settled before M2, since M2 consumes it. It is
also the one item that could reasonably be declared out of scope: a
pods-and-placements manager is a coherent product, and multiplayer Commander
genuinely has no best-of-three. If it's cut, cut it explicitly in the contract
rather than by omission.

### M2 — tiebreakers are one deep

`standings_rows()` computes `opponentPoints` — raw summed opponent points — and
sorts on `(points, opponentPoints, name)`. Real Swiss ranks on percentages with
a floor: opponent match-win percentage, then game-win percentage, then opponent
game-win percentage, with a minimum applied per opponent so that dropping
someone's terrible record doesn't distort the field. The floor differs by
publisher and the ordering of the chain differs by game.

So **the tiebreaker chain belongs in the profile**, as an ordered list of named
breakers the core knows how to compute. Two things to respect: `standings_rows`
does it in one pass with no per-entrant queries, which is worth preserving; and
opponent percentages need a defined answer for byes and dropped players, which
is precisely where hand-rolled implementations go wrong.

Sorting by name last is also a silent tiebreak — a genuine tie should probably
be reported as one.

### M3 — nothing performs a cut

Already recorded as the largest gap in `tournament-api-contract.md` §11.
`GET /{code}/plan` recommends a cut from the profile's bracket; `open_round`
always pairs Swiss. Single elimination needs re-podding, bracket seeding from
standings, and its own time-called rule — in a cut, MTR 2.4 says highest life
*does* decide, which is the one place `highest_resource` is official rather
than a house convention. Every game's structures already declare `cut_to` and
`elim_rounds`, so the profile side is done and the execution is missing.

### M4 — a profile conformance suite

The safety net that makes all of the above hold. One parametrized test module
running over every registered profile, asserting the invariants a profile must
satisfy — resource direction is `up` or `down`; every structure's `pod_size` is
within the profile's legal table sizes; bands ascend and the last is a
sentinel; `time_called_policies[0]` is defined and resource-ranking policies
appear only where the resource is comparable; every mode is one the room layer
implements; `official=True` implies a non-empty `source`.

Write this **first**. It is cheap, it is the spec for a new profile in
executable form, and it turns each item above into a failing test rather than a
review comment.

### M5 — official structures need primary sources

Adding Lorcana or Pokémon means adding `EventStructure`s, and this repo's rule
is that `official=True` requires a published rules document with the citation
recorded in `source`. The MTG entries cite MTR Appendix E with an effective
date; the Commander ones are flagged `official=False` with an explicit note
that Wizards publishes no multiplayer structure.

**Do not fill these tables from memory or from a wiki.** Each game needs its
current organizer/tournament rules PDF read directly, the round-count table
transcribed with its effective date, and anything not in the document marked
`official=False`. If a document can't be found, ship the profile with house
structures honestly labelled — that is what `official` is for. This is
research, not coding, and it can run in parallel with everything else.

### M6 — export

No CSV or JSON export of standings or results
(`tournament-api-contract.md` §11). Small, and the first thing a real organizer
asks for after their event ends.

---

## Suggested order

Grouped so that independent tracks can run in parallel; within a phase, items
don't depend on each other.

**Phase 0 — clear the ground.**
W0: cut the `events-platform.md` references from `AGENTS.md` (3 places) and
`docs/ideas.md` (2), and rewrite the "table layer is frozen" rule so it stands
on its own reasoning rather than citing a document that isn't here. M4: the
conformance suite. M5: begin the rules research — long lead time, no
dependencies.

**Phase 1 — make duels work.** B1 and B2 together, as one change with tests at
pod sizes 2 through 5. Nothing else should land between them; a pairer that
splits correctly but still can't issue a bye is not shippable.

**Phase 2 — de-MTG the core.** L1, L2, L3, L5 in parallel. L4 needs M5's
findings for any game whose notice text isn't already known.

**Phase 3 — a real second game.** Add one profile end to end, hand-scored, no
room support, using only what Phases 0–2 built. **Whether this required
touching anything outside `games.py` and its tests is the acceptance test for
this entire document.** Anything that did is a boundary in the wrong place, and
gets fixed rather than worked around.

**Phase 4 — competitive depth.** M1, then M2. M3 and M6 independently.

---

## Definition of done for a new game

The checklist Phase 3 is measuring against:

1. A `GameProfile` in `games.py` and nothing else in `backend/app/` changed.
2. Structures with real citations, or honestly flagged as house conventions.
3. Publisher attribution text quoted from the primary source, or none.
4. The conformance suite passes with the new profile parametrized in.
5. The organizer can create, pair, score, and finish an event in that game
   without the UI showing a word of MTG vocabulary.
6. `tournament-api-contract.md` §8 updated — it is the file that wins any
   disagreement about what the server serves.

---

## Decisions needed before Phase 4

Not blockers for Phases 0–3, but they shape M1 and M2:

- **Are matches best-of-three, or is a pod result final?** (M1.) Cutting it is
  defensible; leaving it undecided is not.
- **Which tiebreaker chain is the default** for a game whose publisher
  documents none — and is a genuine tie reported as a tie, or broken by name?
- **Does the table layer ever gain a second resource type** — a Lorcana lore
  counter counting up to 20 — or do non-MTG games stay hand-scored? L6 and the
  scope of the frozen table surface both hang on this. Hand-scored first is the
  cheaper answer and is what L3 assumes.
