# Tournament API — contract

What the server *actually* serves, as shipped. `tournament-api-design.md` is the
design that preceded it and has diverged in places; where the two disagree, this
file is right. Divergences are listed in §7 with the reasoning, so the design doc
stays readable as a record of intent.

Base path: `/api/tournament`. All bodies and responses are JSON. Times are Unix
seconds (integers), UTC.

---

## 1. Authentication

Three separate credentials, deliberately unequal:

| Caller | Credential | Carried in | Grants |
|---|---|---|---|
| Organizer | account session | `session` cookie (httpOnly, Secure, SameSite) | full control of tournaments they own |
| Entrant | entrant token | `?token=` query parameter | their own view; calling an official |
| Player in a pod | room token | `X-Player-Token` header (table API) | one seat in one room |

An organizer must own the tournament — `require_organizer` matches the session's
account against `tournaments.organizer_account_id`. Any other account gets 403,
no session gets 401.

**Players are anonymous by design.** `POST /claim` takes no authentication at
all: possession of the tournament code is the gate, and it returns a token
scoped to that tournament. Being signed in changes nothing about what the
tournament learns — `entrants.account_id` is never written. It exists only as a
hook for a future *opt-in* history link, and populating it as a side effect of
a signed-in claim would be a privacy regression, not a convenience. Pinned by
`TestIdentityStaysSeparate`.

**Entrant tokens are query parameters, not headers**, because the player client
reads state from a plain `GET` it can retry cheaply. That places the token in
request URLs, so it must never be logged: the reverse proxy strips query strings
from access logs. A header would be tidier and is the obvious future change.

**Room tokens are seat credentials.** `GET /{code}` returns one only on
`myPod.roomToken`, for the caller's own seat, derived from their entrant token.
It never appears in `pods[]`, which every entrant can read. Three tests in
`test_tournaments.py::TestPlayerView` pin this; treat them as load-bearing.

---

## 2. Lifecycle

### The round clock

There is no clock in a room and nothing syncing one. `trounds.ends_at` is a
single absolute timestamp written when the organizer starts the timer; every
client counts down against it locally, using the server's `now` only to correct
a device whose clock is wrong. Pause records `paused_at`; resume adds the gap
back onto `ends_at`. A pod's `extension_seconds` is added on read, so a judge
extending one table moves only that table.

Because the timer lives on the tournament and players are looking at the *room*,
room state carries a `tournament` block (round, deadline, pause, turns) and
tournament writes that change a clock push to the affected rooms over the
room's existing WebSocket. Without that push a pause is invisible to players —
their timer keeps visibly running.


```
create ──▶ add entrants ──▶ open round ──▶ [play] ──▶ results ──▶ close round ──┐
             ▲                                                                  │
             └──────────────────────── next round ◀─────────────────────────────┘
```

`tournaments.status`: `setup` → `running` (first round opens) → `ended`.
`trounds.status`: `active` → `closed`. `pods.status`: `active` →
`awaiting_result` → `complete`.

Only one round is active at a time. Opening a second while one is active is a
409 unless `reroll` is set.

---

## 3. Endpoints

### `POST /api/tournament`
Create. **Organizer session required, and the account must have an email** —
without one this returns **409**, not 403. Rationale in §6.

```jsonc
// request
{ "name": "Friday Night Commander",   // 1–80 chars
  "mode": "life",                      // life | treachery
  "settings": { "podSize": 4 } }       // unknown keys are dropped, not rejected
// response
{ "code": "K7M2Q" }                    // 5 chars, alphabet excludes I/L/O/0/1
```

### `GET /api/tournament/{code}`
The single snapshot every client polls. Personalized in memory from one query
set — no N+1, no per-viewer queries.

Optional `?token=` (entrant). Organizer recognized by cookie.

```jsonc
{ "tournament": { "code", "name", "mode", "status", "settings", "roundCount" },
  "round": { "number", "status", "endsAt", "pausedAt",
             "now": 1784500123 },      // server clock; clients derive an offset
  "pods": [ { "podId", "table", "status", "roomCode", "extensionSeconds",
              "seats": [ {"seat", "entrantId", "name", "place", "points"} ] } ],
  "myPod": { /* same shape, plus: */ "roomToken": "…", "mySeat": 2 },
  "me": { "entrantId", "name" },       // null when anonymous
  "standings": [ {"entrantId","name","points","opponentPoints",
                  "podsPlayed","claimed","dropped","rank"} ],
  "calls": [ … ],                      // organizer only; [] for everyone else
  "isOrganizer": false }
```

`round.now` exists so clients never trust the local clock — a phone with a wrong
time would otherwise show a wrong round timer. Clients compute
`offset = now*1000 - Date.now()` once per poll.

`standings` is always present and always fully sorted (points, then opponents'
points, then name). Ranks are dense positions after sorting, 1-based.

### `GET /api/tournament/{code}/roster`
**Public and unauthenticated by design** — a player scans a code and needs the
name list before they have any credential.

```jsonc
{ "name": "Friday Night Commander", "status": "running",
  "entrants": [ {"entrantId", "name", "claimed", "dropped"} ] }
```

Exposes display names and claim state only. No tokens, no email, no counts that
aren't already visible in the room.

### `POST /api/tournament/{code}/claim`
Claim a seat. No auth — possession of the tournament code is the only gate.

```jsonc
{ "entrantId": 41 }
→ { "entrantToken": "…", "entrantId": 41, "name": "Ada" }
```

By **id, not name**: names legitimately repeat, ids don't. First claim wins;
a second returns **409**. The organizer can `release` a mis-tap.

`wizardsEmail` is governed by `settings.collectWizardsEmail`:

| Setting | Behaviour |
|---|---|
| `off` *(default)* | any submitted address is **discarded**, not stored |
| `optional` | stored if given |
| `required` | claim fails with **422** without one |

Only sanctioned events reporting to Wizards need this, so it is off by default.
The address is never returned by any endpoint, including the public roster.

### `POST /api/tournament/{code}/entrants`  *(organizer)*
```jsonc
// manual entry
{ "names": ["Ada", "Grace", ""] }      // blanks skipped
// import (idempotent)
{ "entrants": [ {"name": "Ada", "externalRef": "topdeck:9f3c"} ] }
→ { "added":   [ {"entrantId", "name", "externalRef"} ],
    "matched": [ /* already present, name refreshed from upstream */ ] }
```

Both forms may be mixed in one call. Duplicates *without* a ref are allowed —
two people really can be named Ada.

`externalRef` is `"source:id"` and unique per tournament. Re-running an import
matches on it and returns the entrant under `matched` instead of creating a
second row; an upstream rename updates the existing name rather than forking the
person. Never match on display name — that would make names identity, the flaw
we rejected in §7.

### `POST /api/tournament/{code}/entrants/{id}/release`  *(organizer)*
Clears the entrant's token so the seat can be claimed again. Idempotent.

### `POST /api/tournament/{code}/entrants/{id}/drop`  *(organizer)*
### `POST /api/tournament/{code}/entrants/{id}/undrop`  *(organizer)*
`drop` sets `dropped_at`; dropped entrants are excluded from future pairings but
keep their points and history. `undrop` clears it and they are paired again —
people come back, and a mis-keyed drop shouldn't end someone's day. Both
idempotent.

### `POST /api/tournament/{code}/end`  *(organizer)*
Ends the event and freezes standings. **409** if a round is still open; after
this, opening a round is **409**.

```jsonc
→ { "ok": true, "standings": [ … ] }
```

### `POST /api/tournament/{code}/rounds`  *(organizer)*
Pair, seat, and create one room per pod.

```jsonc
{ "reroll": false }  → { "round": 2, "pods": 3 }
```

- `reroll: false` with a round already active → **409**.
- `reroll: true` discards the current round's pods and re-pairs with an
  incremented seed. Only sane before play starts; the API does not stop you.
- No undropped entrants → **400**.

Pairing is deterministic given `(field, points, met, seed)`. Everything is
computed and persisted before the round is announced, so opening a round is a
broadcast of settled state rather than work done while clients poll.

Pod sizes never fall below 3 — remainders of 1–2 are absorbed into neighbours.

### `POST /api/tournament/{code}/rounds/time`  *(organizer)*
Call time on the round. Every pod without a result is decided by
`settings.timeCalledPolicy`; pods already reported are untouched, and an
organizer ruling is never overwritten.

```jsonc
→ { "ok": true, "decided": 3, "policy": "draw_all" }
```

| Policy | Behaviour |
|---|---|
| `draw_all` *(default)* | every unfinished pod is a draw |
| `draw_survivors` | players still alive draw; eliminated rank below in death order |
| `highest_life` | survivors ranked on life, **equal life is a genuine tie**; eliminated below |
| `organizer_decides` | pods move to `awaiting_result`; nothing automatic |

`draw_all` is the default because **MTR 2.4 makes a match that goes to time a
draw** — life totals do not rank it outside single elimination. The other
policies are house rules that leagues really do run, so they are opt-in and
named for what they are rather than presented as official.

Eliminated players never outrank survivors, whatever their life total was when
they died.

**Time called does not decide the pod.** MTR 2.4: the current turn is finished
and five additional turns are played, and only an incomplete game *after* them
is a draw. So `rounds/time` puts each pod into `extra_turns` with a countdown;
the policy applies when the count reaches zero. A pod with no room to count in
is decided immediately rather than stranded.

### `POST /api/tournament/{code}/pods/{pod_id}/turn`
```jsonc
{ "delta": -1 }   // -1 counts a turn; +1 undoes a mis-tap or adds a turn
→ { "ok": true, "turnsRemaining": 4, "decided": false }
```
Any player at the table may call this with their entrant token — a judge should
not have to stand there for five turns. The app cannot detect a turn passing;
the table counts them, which is what players already do by hand.

The count may exceed where it started: MTR 2.6 says certain slow-play penalties
add turns rather than time, and those are added to the end-of-match additional
turns.

### `POST /api/tournament/{code}/rounds/close`  *(organizer)*
Refuses with **409** if any pod lacks a result, or any official call is still
open. Both messages name the count.

### `POST /api/tournament/{code}/pods/{pod_id}/result`  *(organizer)*
```jsonc
{ "kind": "placement",                 // placement | draw | unfinished
  "places": [ {"entrantId": 41, "place": 1} ],
  "note": "ruled a draw at time",
  "expectedVersion": 2 }               // optional optimistic-concurrency guard
→ { "ok": true, "version": 3 }
```

Results are **versioned, never mutated** — an override appends. If
`expectedVersion` is supplied and doesn't match the current max, **409**
("someone else recorded a result — reload before overriding"). Omit it to force.

Points come from `settings.scoring` (`win_draw_loss` or `placement`) and are
written onto `pod_seats` at decision time, so changing scoring settings
mid-event does not silently rewrite history.

### Automatic results (no endpoint)
When a game ends in a pod's room, the room reports placement from **elimination
order** — last standing is 1st. Written with `source: "auto"`.

**An `auto` result never overwrites an `organizer` one.** The reverse is allowed:
that's what override means. This is the least-tested path in the system (§8).

### `POST /api/tournament/{code}/timer`  *(organizer)*
```jsonc
{ "action": "start", "minutes": 60 }   // start | pause | resume | extend
{ "action": "extend", "minutes": 5, "podId": 12 }   // one table only
```
- `start` without `minutes` uses `settings.roundMinutes`.
- `resume` adds the paused duration to `endsAt`, so a pause never eats clock.
- `extend` **with** `podId` adds to that pod's `extensionSeconds`; **without**,
  extends the whole round.
- No active round → **409**. Unknown action → **400**.

### `POST /api/tournament/{code}/pods/{pod_id}/call?token=…`  *(entrant)*
```jsonc
{ "category": null, "note": "judge please" }
→ { "ok": true, "callId": 7, "alreadyOpen": true }   // when one is already open
```
**One open call per pod.** A second returns the existing `callId` with
`alreadyOpen: true` rather than queueing duplicates — four players tapping the
same button must not summon four judges. Disabled tournaments return **409**.

The token is optional; an anonymous call records `entrant_id: null`. A table
with a problem should be able to raise a hand even if a phone lost its token.

### `POST /api/tournament/{code}/calls/{id}/ack`  *(organizer)*
### `POST /api/tournament/{code}/calls/{id}/resolve`  *(organizer)*
**A judge call never stops the round clock — it stops the table.** Everyone
else keeps playing, so that table has lost time the others haven't, and the
extension exists to give it back. (`timer` `pause` is the separate, rarer case
of stopping the round for the whole room.)

Resolving therefore measures the disruption — hand up to ruling done — and
gives that table the time back automatically:

```jsonc
{ "note": "ruled" }                    // omit extendMinutes: give back what was measured
→ { "openSeconds": 250, "suggestedMinutes": 5,
    "grantedMinutes": 5, "grantedBy": "measured" }

{ "extendMinutes": 0 }                 // judge overrides, including down to nothing
{ "extendMinutes": 11 }                // deck check: duration plus three minutes
```

`grantedBy` is `measured`, `judge`, or `off`. Under a minute grants nothing —
MTR 2.6 sets the bar at *more than one minute*. A judge can always override,
because "appropriately" is their call and only they know a deck check's
duration-plus-three formula applies. Setting `autoExtendOnCall: false` reverts
to granting nothing unless asked.

`ack` = "on my way" (only affects `open` calls). `resolve` closes it and stores
`note` as the resolution. Both idempotent and both return `{"ok": true}` even
when nothing matched — a judge double-tapping should not see an error.

---

## 4. Errors

`{"detail": "message"}`, with the HTTP status carrying the meaning:

| Status | Means |
|---|---|
| 400 | malformed input, or nothing to pair |
| 401 | no session where one is required |
| 403 | authenticated, but not this tournament's organizer |
| 404 | no such tournament / pod |
| 409 | **state conflict** — seat claimed, round open, result superseded, calls outstanding, organizer has no email |

409 is doing a lot of work on purpose: nearly every one is recoverable by the
caller re-reading state, and the messages are written to be shown to a human
verbatim.

---

## 5. Rate limiting

Shared limiter (`limits.py`). Tournament paths classify as `normal`
(900 req / 60 s per client) except `POST /claim` and account endpoints, which
are `sensitive` (20 / 600). Clients are identified by a salted HMAC of the IP —
pseudonymous, never the raw address. Repeat offenders escalate 1h → 6h → 24h → 7d.

Polling at 5 s (30 s hidden) with ~50 attendees is ~10 req/s — two orders of
magnitude inside the limit.

---

## 6. Why hosting requires an email

Every other part of the app works with no email, and accounts are optional
throughout. Hosting is the exception: an organizer locked out mid-event strands
every table, and recovery codes are no help when they're in a drawer at home.
It is enforced at create time (**409**), never at signup, so the requirement
lands on the person choosing to host rather than on everyone.

The address is stored plainly and used only for recovery. It is never returned
by any endpoint — `/api/account/me` exposes `hasEmail: bool`, not the value.

Usernames, by contrast, cannot be encrypted: they're looked up on every sign-in,
and searchable encryption means deterministic encryption or a blind index, both
of which leak equality. That's why signup discourages email-as-username — a
warning, not a block.

---

## 7. Divergences from `tournament-api-design.md`

| Design | Shipped | Why |
|---|---|---|
| `GET /rounds/latest`, `/standings`, `/calls` | folded into `GET /{code}` | three polls became one snapshot; cheaper and race-free |
| `/tables/{id}` | `/pods/{pod_id}` | "pod" is the word players use |
| `WS /{code}/ws` | not built | polling is enough at this scale and costs nothing idle; see §8 |
| `GET /rounds/{n}` (history) | not built | nothing needs it yet |
| organizer secret returned once | account session + email | recoverable; a lost secret mid-event is unrecoverable |
| — | `POST /rounds/close` | the design had no way to end a round |
| — | `entrants/{id}/release`, `/drop` | mis-taps and departures both happen constantly |

---

## 8. Game profiles

The core is game-agnostic. Entrants, rounds, pods, seats, placements,
standings, timers and judge calls are true of any tabletop event, and none of
that code knows what Magic is. **MTG is a profile over the core, not the base
of it.**

What varies by game lives in `games.py` as a `GameProfile`:

| Field | Meaning |
|---|---|
| `default_pod_size` | seats at a table — 4 for multiplayer Commander, 2 for a duel |
| `default_round_minutes` | round length |
| `resource`, `resource_start`, `resource_direction`, `resource_goal` | what players track and which way it moves: MTG counts life *down* from 40 to 0; a game like Lorcana counts lore *up* to a target |
| `modes` | room modes valid for this game; empty means no live table state, scored by hand |
| `time_called_policies` | offered policies, first is the default |
| `sanctioning_account` | label for the publisher account email, or `None` |

### `GET /api/tournament/games`
```jsonc
{ "games": [ { "key": "mtg", "name": "Magic: The Gathering",
               "publisher": "Wizards of the Coast", "defaultPodSize": 4,
               "modes": ["life", "treachery"], "resource": "life",
               "timeCalledPolicies": [ … ], "sanctioningAccount": "Wizards account email" } ] }
```

`POST /api/tournament` takes `game` (default `"mtg"`) and validates `mode` and
`timeCalledPolicy` against that profile — a game is rejected with the list of
what this server runs, rather than silently accepting nonsense.

`tournaments.game` is `NOT NULL DEFAULT 'mtg'`, so the migration backfilled
existing events rather than leaving nulls. `profile_for()` still degrades to
the default for an unrecognised string, so a row written by a newer build
cannot 500 an older one.

### Adding a game

1. Add a `GameProfile` to `games.py` and register it.
2. If it needs live table state, add a room mode; if not, leave `modes` empty
   and organizers report results by hand — which already works.
3. Nothing in `tournaments.py` should need editing. If it does, that is the
   bug: the fact belongs in the profile.

**Deliberately not in a profile:** anything resembling a rules engine. A profile
supplies defaults and vocabulary; it never adjudicates a game.

**Known MTG leakage still to clean up:** the settings key `startingLife` keeps
its name because the room API already speaks it and renaming a live key buys
nothing today — read it as "the profile's resource start". Likewise
`collectWizardsEmail` is really "publisher account email", and the
`highest_life` policy is really "highest resource". Rename them together when a
second game lands, not before.

---

## 9. Interoperability

The resource hierarchy intentionally mirrors
[TopDeck Tournaments V2](https://topdeck.gg/docs/tournaments-v2) so an import
adapter is a field rename rather than a translation layer:

| Theirs | Ours | Note |
|---|---|---|
| `tournament` | `tournament` | ours adds `mode`, `settings`, bound rooms |
| `rounds[]` | `trounds` | `number` is always an integer (see below) |
| `tables[]` | `pods` | rename only; a pod is a table with N players |
| `players[]` | `pod_seats` | ours adds `seat` = turn order |
| `winner_id` | `pod_results.places[]` | typed, ordered, multi-place |
| — | `entrants.external_ref` | `"source:id"`, makes imports re-runnable |

**Where we deliberately differ**, and what an adapter must therefore do:

| Their shape | Adapter must | Why ours differs |
|---|---|---|
| `winner_id: "Draw"` | map to `kind: "draw"` | a magic string in an id field forces every client to special-case it |
| `winner` name beside `winner_id` | discard the name | results denormalized onto display names, which change |
| `round: "Top 8"` | map to an integer + a cut flag | union-typed fields via magic values |
| `table: "Byes"` | map to `kind: "bye"` | same |
| single `winner` per pod | expand to `places[]` | can't express placement, survival points, or a time-called draw |

**Imports are one-way.** TopDeck's API cannot accept results, so pairings can
flow in but our results stay local. Any UI that offers an import has to say this
plainly, or organizers will assume a sync that does not exist.

No adapter ships yet — `external_ref` and this mapping are the groundwork so
that adding one later doesn't require a migration of live event data.

---

## 10. Known gaps

- **Auto-result is test-covered, not event-proven.** The room → placement path
  has never run in a real game inside a tournament pod. Prove it with a
  throwaway 4-player event before running anything that counts.
- **No WebSocket.** Timer updates lag by up to one poll (5 s foreground).
- **No top cut / playoff re-podding**, and no `rounds: auto` recommendation.
  These are the largest remaining gaps for running a full competitive event.
- **No entrant rename** outside an import.
- **No import adapter** yet; the data model is ready for one (§9).
- **`/openapi.json` and `/docs` are publicly served**, enumerating every route
  and schema. Authentication still holds, but it's free reconnaissance on an
  otherwise hardened box. Disable with
  `FastAPI(openapi_url=None, docs_url=None)` in `main.py`, or gate them behind
  the organizer session.
