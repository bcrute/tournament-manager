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

### `GET /api/tournament/mine`  *(organizer)*
Tournaments owned by the calling account, most recently active first. Account
session required; scoped to the caller, never to all events.

### `GET /api/tournament/{code}/plan`
Advisory only. Returns the structure recommended for the current field —
round count and, where the game profile defines a bracket, a suggested cut.
**Nothing acts on it**: `open_round` always runs Swiss, and no setting stores
the answer. It exists so an organizer can see what a field of this size would
usually be run as, not to configure the event.

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
  "sanctioning": { "collect": "required", "label": "Wizards account email" },
  "entrants": [ {"entrantId", "name", "claimed", "dropped"} ] }
```

Exposes display names and claim state only. No tokens, no email, no counts that
aren't already visible in the room.

`sanctioning` is what the claim form needs and the only place it can get it: the
player has no credential yet. `collect` is the event's `collectSanctioningId`,
and `label` is the game profile's `sanctioning_account` — the wording to put on
the field. `collect` is `"off"` and `label` is `null` for a game with no
sanctioning body, whatever the stored setting says.

### `POST /api/tournament/{code}/claim`
Claim a seat. No auth — possession of the tournament code is the only gate.

```jsonc
{ "entrantId": "kZ8vQ1nR" }
→ { "entrantToken": "…", "entrantId": "kZ8vQ1nR", "name": "Ada" }
```

**`entrantId` is an opaque random string, tournament-scoped.** The integer
primary key never leaves the server: the roster is readable by anyone holding a
tournament code, and a sequential id would disclose roughly how many entrants
the platform has ever created. Posting an internal id where a public one belongs
is a 404, not a silent hit on the same row, and a public id from another
tournament does not resolve. Pinned by `TestEntrantIdsAreOpaque`.

By **id, not name**: names legitimately repeat, ids don't. First claim wins;
a second returns **409**. The organizer can `release` a mis-tap.

`sanctioningId` is governed by `settings.collectSanctioningId`:

| Setting | Behaviour |
|---|---|
| `off` *(default)* | any submitted id is **discarded**, not stored |
| `optional` | stored if given |
| `required` | claim fails with **422** without one |

Only a sanctioned event needs this, so it is off by default. The id is never
returned by any endpoint, including the public roster.

**Every word the server says about the id comes from the game profile's
`sanctioning_account`** — the 422 reads "this event is sanctioned, so it needs
your {label}". A profile whose `sanctioning_account` is `None` has no such
concept: `POST /api/tournament` **rejects** `collectSanctioningId` of `optional`
or `required` for that game with **400**, and if a row somehow carries one
anyway the claim treats it as `off` rather than demanding an id the server
cannot even name. Any value other than `off | optional | required` is a **400**
on create, not a silent "not off".

*Deprecated, still accepted:* the body field `wizardsEmail` and the settings key
`collectWizardsEmail`, which is rewritten to `collectSanctioningId` on create
(the new key wins if both are sent, and only the new one is stored). Shipped
clients still send both spellings.

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
→ { "ok": true, "standings": [ … ] }   // identical shape and sort to GET /{code}
```

`standings` here is the same translated rows the snapshot serves, opaque
`entrantId` included — a frozen final table that disagreed with the snapshot
players are still polling would be worse than either. Pinned by
`TestEndReturnsPublicIds`.

### `POST /api/tournament/{code}/rounds`  *(organizer)*
Pair, seat, and create one room per pod — unless the game's profile has no
modes, in which case the pods are seated roomless and the organizer reports each
result by hand (§8). Such a pod's `roomCode` and `roomToken` are `null`
everywhere they appear, and time called decides it straight away, since there is
no live table state to rank or turns to count.

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
| `highest_resource` | survivors ranked on the profile's resource, **an equal total is a genuine tie**; eliminated below. `highest_life` is accepted as an alias — it is persisted in running events' settings — and stored as `highest_resource` |
| `organizer_decides` | pods move to `awaiting_result`; nothing automatic |

`draw_all` is the default because **MTR 2.4 makes a match that goes to time a
draw** — life totals do not rank it outside single elimination. The other
policies are house rules that leagues really do run, so they are opt-in and
named for what they are rather than presented as official.

Eliminated players never outrank survivors, whatever their resource total was
when they died.

Which way `highest_resource` sorts comes from the profile, not from the code:
`resource_goal` is the value that ends the game for the player who reaches it
and `resource_direction` is the way the resource travels there, so the player
*furthest from* that value ranks first. MTG life counts down to 0, so 30 beats
12; a resource counting up to its goal ranks the other way and 2 beats 9. The
note written onto the result is worded from the profile's resource name —
`time called — ranked on life` for MTG.

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
the table counts them, which is what players already do by hand. The organizer
may also count for a table, which is the fallback when a pod has no working
phone between them.

The count may exceed where it started: MTR 2.6 says certain slow-play penalties
add turns rather than time, and those are added to the end-of-match additional
turns.

### `POST /api/tournament/{code}/rounds/close`  *(organizer)*
Refuses with **409** if any pod lacks a result, or any official call is still
open. Both messages name the count.

### `POST /api/tournament/{code}/pods/{pod_id}/result`  *(organizer)*
```jsonc
{ "kind": "placement",                 // placement | draw | unfinished
  "places": [ {"entrantId": "kZ8vQ1nR", "place": 1} ],
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

**The token is required, and must belong to someone seated at that table.**
A caller who is not seated in the pod gets **403**. This reverses an earlier
decision that allowed anonymous calls so a player whose phone lost its token
could still raise a hand: because resolving a call grants that table a time
extension, an anonymous call let a stranger holding the tournament code aim
free time at any pod. At a physical event the fallback is raising an actual
hand. See `docs/security.md`, "Audit, 2026-07-19".

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

Playing needs neither an account nor an email, anywhere in the app. Hosting
needs both: an organizer locked out mid-event strands every table, and recovery
codes are no help when they're in a drawer at home. "Accounts are optional" is
true of players and false of organizers, so the UI never says it unqualified.
It is enforced at create time (**409**), never at signup, so the requirement
lands on the person choosing to host rather than on everyone.

The address is stored plainly and used only for recovery. It is never returned
by any endpoint — `/api/account/me` exposes `hasEmail: bool`, not the value.

Usernames, by contrast, cannot be encrypted: they're looked up on every sign-in,
and searchable encryption means deterministic encryption or a blind index, both
of which leak equality. That's why signup discourages email-as-username — a
warning, not a block.

---

## 6a. Settings, as actually accepted

`settings` is a JSON blob, but it is **whitelist-filtered on create** against
the defaults for the chosen game, so a key that is not in this table cannot be
stored at all (`tournaments.py`, `cfg = {k: v for k, v in body.settings.items()
if k in allowed}`). Create is the only write path — there is no
update-settings endpoint, so an event's settings are fixed once it exists.

Every key below is read by code. That is the standard: **this table and the
defaults dict must agree, and a key appears here only once something reads it.**

Two keys are *validated* rather than merely filtered, and a bad value is a
**400** rather than a silent default: `timeCalledPolicy` must be one the game
profile offers, and `collectSanctioningId` must be `off | optional | required`
and may only be non-`off` for a game whose profile has a `sanctioning_account`.
One deprecated spelling survives the filter by being rewritten to its current
name before it: `collectWizardsEmail` → `collectSanctioningId`.

| Key | Read by |
|---|---|
| `scoring`, `winPoints`, `drawPoints`, `lossPoints`, `placementPoints`, `byeScoring` | `points_for`, at result-decision time |
| `podSize` | `pair_round(preferred_size=…)`, and the recommended structure |
| `seatAssignment` | `seat_pods(mode=…)` |
| `structure` | `structure_for(…)` |
| `roundMinutes` | `timer` `start` when no `minutes` given |
| `timeCalledPolicy` | `rounds/time`, and pod resolution when extra turns run out |
| `extraTurns` | `rounds/time`, drives the countdown and `extra_turns` status |
| `collectSanctioningId` | `claim`, and `roster` to advertise the label |
| `allowOfficialCalls` | the call endpoint, and the player UI |
| `autoExtendOnCall` | `calls/{id}/resolve` |
| `startingLife` | creating each pod's room. Read it as "the profile's resource start" |

**Unknown keys are dropped silently, and that is a sharp edge.** A client
posting a setting this server does not implement gets **200** and no effect.
`tournament-api-design.md` §7 describes several that were designed and never
built (`topCutSize`, `topCutPolicy`, `turnExtensionMinutes`, `organizerAuth`,
`spectatorView`, `staffRoles`, `rounds`); they are marked there. Anything added
to the defaults dict must be read by something in the same change — a settings
key with no code behind it is the failure mode `AGENTS.md` names, and silent
filtering makes it invisible from the outside rather than merely inert.

## 7. Divergences from `tournament-api-design.md`

| Design | Shipped | Why |
|---|---|---|
| `GET /rounds/latest`, `/standings`, `/calls` | folded into `GET /{code}` | three polls became one snapshot; cheaper and race-free |
| `/tables/{id}` | `/pods/{pod_id}` | "pod" is the word players use |
| `WS /{code}/ws` | not built | the room WebSocket carries tournament clock pushes to the players who need them; a second channel earned nothing |
| `GET /rounds/{n}` (history) | not built | nothing needs it yet |
| organizer secret returned once | account session + email | recoverable; a lost secret mid-event is unrecoverable |
| anonymous official calls allowed | seated entrant token required | resolving a call grants time; anonymous let a stranger aim it at any table |
| organizer-named pods, drag-to-assign | neither built | automated pairing landed first and covered the need; pods are numbered |
| — | `POST /rounds/close` | the design had no way to end a round |
| — | `entrants/{id}/release`, `/drop`, `/undrop` | mis-taps and departures both happen constantly |
| — | `GET /mine`, `GET /{code}/plan` | an organizer needs to find their own events, and to see what a field this size is usually run as |

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
| `resource`, `resource_start`, `resource_direction`, `resource_goal` | what players track and which way it moves: MTG counts life *down* from 40 to 0; a resource that counts *up* to its goal (poison, corruption) ranks the other way. All four are emitted by `/games` and the direction drives `highest_resource` ranking |
| `modes` | room modes valid for this game; empty means no live table state, scored by hand |
| `time_called_policies` | offered policies, first is the default |
| `sanctioning_account` | label for the id a sanctioned event collects, and the only wording the server uses for it. `None` means the game has no sanctioning body, and `collectSanctioningId` cannot be turned on |

### `GET /api/tournament/games`
```jsonc
{ "games": [ { "key": "mtg", "name": "Magic: The Gathering",
               "publisher": "Wizards of the Coast", "defaultPodSize": 4,
               "modes": ["life", "treachery"], "resource": "life",
               "resourceStart": 40, "resourceDirection": "down", "resourceGoal": 0,
               "timeCalledPolicies": [ … ], "sanctioningAccount": "Wizards account email" } ] }
```

`POST /api/tournament` takes `game` (default `"mtg"`) and validates `mode` and
`timeCalledPolicy` against that profile — a game is rejected with the list of
what this server runs, rather than silently accepting nonsense. `mode` may be
omitted; it then becomes the profile's first mode. A profile with **no** modes
accepts no `mode` at all: supplying one is **400**, and the stored value is the
empty string. Rounds in such an event create no rooms.

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
nothing today — read it as "the profile's resource start". The `highest_life`
policy *has* been renamed to `highest_resource`; the old spelling stays
accepted as an alias because it is sitting in the settings JSON of tournaments
that are running right now. The `entrants` column behind `collectSanctioningId`
is still called `wizards_email`; it is internal, never served, and its rename is
pending only because a test reads it by name.

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
- **No tournament WebSocket.** Tournament state is polled (5 s foreground,
  30 s hidden), so standings and roster changes lag by up to one poll. Clock
  changes do not: they are pushed over each pod room's existing socket,
  because a pause a player cannot see is a timer that visibly keeps running.
- **No top cut / playoff re-podding.** `GET /{code}/plan` will *recommend* a
  cut from the game profile's bracket, but nothing performs one — there is no
  single-elimination path and `open_round` always pairs Swiss. This is the
  largest remaining gap for running a full competitive event.
- **No manual pod assignment.** An organizer cannot move an entrant between
  pods or name a table; the only route into a pod is the pairer. Re-roll
  exists in the API but has no UI control.
- **No CSV/JSON export** of standings or results.
- **No entrant rename** outside an import.
- **No import adapter** yet; the data model is ready for one (§9).
- **Tournaments never expire.** Rooms belonging to a live tournament are exempt
  from the 3 h idle sweep, which is what keeps a pod alive over lunch — but
  nothing expires the tournament itself. `tournaments.IDLE_TIMEOUT` is defined
  and read by nothing; either wire it up or delete it.
