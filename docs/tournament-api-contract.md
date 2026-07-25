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
request URLs, so it must never be logged. Two things write request targets down
and neither can redact the other's log, so both redact their own: the app
replaces credential-looking query values before any handler sees the record
(`backend/app/access_log.py`, installed at import in `main.py` — uvicorn's
access log is on by default and would otherwise write `?token=…` to the
container log), and the vhost this repo ships (`deploy/caddy/sites/mtg.caddy`)
filters the same parameter out of Caddy's access log. Either way the path and
the parameter *name* survive; only the value becomes `REDACTED`. Pinned by
`test_token_logging.py`. A header would be tidier and is the obvious future
change.

**Room tokens are seat credentials.** `GET /{code}` returns one only on
`myPod.roomToken`, for the caller's own seat, derived from their entrant token.
It never appears in `pods[]`, which every entrant can read. Three tests in
`test_tournaments.py::TestPlayerView` pin this; treat them as load-bearing.

The same rule holds on the WebSocket, and by construction rather than by
repetition: `WS /ws/{code}` personalizes every push through the one function
the poll uses (`personalize_tournament`), so a fanout cannot develop its own
idea of who may see a room token or a room code.
`test_tournament_ws.py::TestTournamentSocket` pins that too.

---

## 2. Lifecycle

### The round clock

There is no clock in a room and nothing syncing one. `trounds.ends_at` is a
single absolute timestamp written when the organizer starts the timer; every
client counts down against it locally, using the server's `now` only to correct
a device whose clock is wrong. Pause records `paused_at`; resume adds the gap
back onto `ends_at`. A pod's `extension_seconds` is added on read, so a judge
extending one table moves only that table: the stored round deadline is never
mutated by an extension. Both read paths apply it — the room's
`tournament.endsAt` and each `pods[].endsAt` in the tournament snapshot. A
client shows a table's clock from that per-pod `endsAt`; `round.endsAt` is the
round's own deadline and is short by the extension for an extended table.

Because the timer lives on the tournament and players are looking at the *room*,
room state carries a `tournament` block (round, deadline, pause, turns) and
tournament writes that change a clock push to the affected rooms over the
room's existing WebSocket. Without that push a pause is invisible to players —
their timer keeps visibly running. The same write also goes out on the
tournament socket (§3), which is what a client not sitting in a pod — the
organizer's board, a player between rounds — is watching.


```
create ──▶ add entrants ──▶ open round ──▶ [play] ──▶ results ──▶ close round ──┐
             ▲                                                                  │
             └──────────────────────── next round ◀─────────────────────────────┘
```

`tournaments.status`: `setup` → `running` (first round opens) → `ended`, or
→ `expired` (idle sweep, §10). `ended` is the organizer's decision and freezes
final standings; `expired` is the server retiring an abandoned event. Both are
terminal and both refuse a new round with a 409; neither hides standings.
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
**It configures nothing**: rounds are opened one at a time by the organizer,
and no setting stores the answer. It exists so an organizer can see what a
field of this size would usually be run as. The one place it is *acted* on is
`POST /{code}/cut` with no size, which runs the cut it recommends.

### `GET /api/tournament/{code}`
The single snapshot every client polls. Personalized in memory from one query
set — no N+1, no per-viewer queries.

Optional `?token=` (entrant). Organizer recognized by cookie.

```jsonc
{ "tournament": { "code", "name", "mode", "status", "settings", "roundCount" },
  "round": { "number", "status", "kind": "swiss",   // swiss | elimination
             "endsAt", "pausedAt",
             "now": 1784500123 },      // server clock; clients derive an offset
  "pods": [ { "podId", "table", "name", "status", "roomCode", "extensionSeconds",
              "endsAt",                  // round.endsAt + this pod's extension
              "seats": [ {"seat", "entrantId", "name", "place", "points"} ] } ],
  "myPod": { /* same shape, plus: */ "roomToken": "…", "mySeat": 2 },
  "me": { "entrantId", "name" },       // null when anonymous
  "standings": [ {"entrantId","name","points","opponentPoints",
                  "podsPlayed","claimed","dropped","rank"} ],
  "cut": { "cutTo": 8, "rounds": 2, "champion": null,   // null until a cut
           "seeds": [ {"entrantId","name","seed":1,"alive":true} ] },
  "calls": [ … ],                      // organizer only; [] for everyone else
  "isOrganizer": false }
```

`round.now` exists so clients never trust the local clock — a phone with a wrong
time would otherwise show a wrong round timer. Clients compute
`offset = now*1000 - Date.now()` once per poll.

`pods[].endsAt` (and `myPod.endsAt`) is the deadline for *that* table: the
round's `endsAt` with the pod's `extensionSeconds` already added, or `null`
when the round timer has not been started. It is what a table's countdown
should use — `extensionSeconds` stays alongside it so the UI can say a table
was extended, not so the client can do the addition itself.

`standings` is always present and always fully sorted (points, then opponents'
points, then name). Ranks are dense positions after sorting, 1-based. **A cut
does not re-order them** — points are what they measure, and a bracket is not
decided on points; who is still in it, and who won it, are in `cut`.
`cut.champion` is set only once the last bracket round is closed with one
player left standing.

`pods[].name` is the organizer's label for the table (§3, *seating overrides*)
and is `null` until one is set. `table` is the number and stays the pod's
identity either way — clients show the name and keep the number beside it.

### `GET /api/tournament/{code}/rounds/{n}`
One round as it was — its pairings, pods, seats and results. The snapshot above
carries only the latest round, so this is the only way to answer "who did I play
in round 1?" once round 2 has opened. **404** for a round this tournament never
had.

Read access is exactly `GET /{code}`'s: possession of the code is the gate,
`?token=` personalizes, the organizer is recognized by cookie. A past round
exposes nothing it did not already expose while it was live, so nothing narrower
would be protecting anything.

```jsonc
{ "round": { "number", "status", "endsAt", "pausedAt", "now" },
  "pods": [ { /* the snapshot's pod shape, plus: */
              "result": { "kind", "source", "version", "decidedAt",
                          "note": "…" } } ],   // note: organizer only
  "myPod": { /* same, plus "roomToken", "mySeat" */ },
  "me": { "entrantId", "name" },
  "isOrganizer": false }
```

The pod view is built by the same code as the snapshot's, so the three rules in
§1 hold here identically: `roomCode` is organizer-only (plus the caller's own
pod), `roomToken` appears only on `myPod`, and `entrantId` is always the public
id. `result` is the latest version — an override appends rather than mutates —
and it is carried because a draw awards every seat place 1, so seat placings
alone cannot tell a drawn pod from a four-way win. `result` is `null` for a pod
with no ruling yet. The organizer's `note` is a ruling written for staff and is
omitted for everyone else.

### `WS /api/tournament/ws/{code}`
The same state, pushed. Anything that changes the event — entrants added,
seats claimed or released, drops, a round opened, re-rolled or closed, results
(organizer *and* automatic), the timer, time called, extra turns, official
calls — sends every connected client a message.

```jsonc
{ "type": "state", "state": { /* exactly the GET /{code} body, per viewer */ } }
{ "type": "update" }   // no state to send (unknown code): refetch and see why
```

One `state` arrives on connect, so a client that joins mid-round does not wait
for the next change. Send `{"token": "…"}` to identify the entrant behind the
socket — in a message, never in the URL, so it cannot reach an access log — and
that socket's next and every later push carries their `me` and `myPod`. The
organizer is recognized by the session cookie sent with the handshake, and the
session is re-read on every push: a socket left open past sign-out drops to an
ordinary viewer's state rather than keeping the organizer's.

**Additive, never load-bearing.** `GET /{code}` still answers exactly as before
and no client is required to hold a socket open. A dropped socket degrades to a
slower client, not a stuck one, so polling is the floor rather than the fallback.

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

### `POST /api/tournament/{code}/entrants/{id}/rename`  *(organizer)*
```jsonc
{ "name": "Ada" }                      // 1–80 chars; blank after trim → 400
→ { "ok": true, "entrantId": "…", "name": "Ada" }
```

Changes the display name and **nothing else**: the entrant token stays valid,
the public id is unchanged, and every recorded place, point and pairing survives
— they all key on the id, never the name. Duplicate names are accepted for the
same reason the import path refuses to match on them (§7): names repeat, ids
don't.

It does **not** rewrite the player rows of a pod already seated. A room seat is
a separate identity — a player renaming themselves inside a room does not touch
their entrant either — so an in-progress game keeps the name it was seated
under, and the new name appears on the roster and standings at once and on the
next round's seats. Unknown id, or an internal integer id, is **404**.

### `GET /api/tournament/{code}/export`  *(organizer)*
Download the event's numbers. `?what=standings|results|all` (default
`standings`), `?format=json|csv` (default `json`). Both responses carry
`Content-Disposition: attachment`.

```jsonc
// format=json
{ "tournament": { "code", "name", "game", "status" },
  "exportedAt": 1784500123,
  "standings": [ { /* as in GET /{code} */ } ],
  "results":   [ {"round","table","podId","podStatus","seat","entrantId","name",
                  "place","points","kind","source","version","note"} ] }
```

`results` is **one row per seat**, not per pod: a result is an ordering over
players, and a flat row per player is what a spreadsheet and a scorekeeper both
want. Where a pod has been overridden, the export carries the **latest** version
only — the same rule standings follow.

**`entrantId` is the public id in every format**, never the integer primary key
(§3, claim). A file outlives the event and gets mailed around, so it is the last
place to make an exception. Pinned by
`test_rename_and_export.py::TestExport::test_export_only_ever_carries_public_ids`.

CSV is written with the stdlib writer, so names containing commas, quotes and
newlines round-trip. Text cells (`name`, `note`, `entrantId`) that begin with
`=`, `+`, `-`, `@` or a control character are prefixed with `'`: entrant names
are free text typed at a shop counter, and a spreadsheet would otherwise
evaluate `=HYPERLINK(…)` on the organizer's machine. The stored name is not
changed — the guard is a rendering concern of the file only.

- `format=csv` with `what=all` → **400**; a CSV file is one table.
- Any other `what` or `format` → **400**.
- An event with no rounds exports a header row, not a 404.

Organizer-only, even though roster and standings are readable with the
tournament code alone: a bulk file is not the same disclosure as a screen.

### `GET /api/tournament/import/sources`
```jsonc
{ "sources": [ {"key": "topdeck", "name": "TopDeck Tournaments V2",
                "docs": "https://topdeck.gg/docs/tournaments-v2",
                "oneWay": true, "acceptsResults": false} ],
  "oneWay": true,
  "note": "Imports are one-way. …" }
```
`oneWay` is on every row as well as the envelope, so a client cannot render the
list without the fact attached to each source. See §9.

### `POST /api/tournament/{code}/import`  *(organizer)*
```jsonc
{ "source": "topdeck",
  "payload": { /* their export, exactly as it came out of their API */ },
  "dryRun": false }                    // true: validate and report, write nothing
→ { "source": "topdeck", "sourceName": "TopDeck Tournaments V2",
    "name": "Friday Duels", "oneWay": true, "note": "Imports are one-way. …",
    "dryRun": false,
    "entrants": { "added": [ {"entrantId","name","externalRef"} ],
                  "matched": [ /* already here, name refreshed */ ] },
    "rounds": [ {"number": 3, "kind": "elimination", "cutTo": 8, "pods": 4,
                 "byes": 0, "results": 4, "awaiting": 0, "skipped": false} ],
    "cutSeeded": 8 }
```

The **payload is read by an adapter**, never by the endpoint: the adapter names
the source's shape, the endpoint knows only entrants, rounds, pods, seats and
kinds (§9 for the mappings, `app/importers.py` for the readers). Adding a second
source is a new adapter and no change to the tournament code.

Entrants go through the same idempotent `externalRef` match as
`POST /{code}/entrants`, so a re-run finds the same people. **`account_id` is
never written** — an import creates entrants, not identities (§1).

Rounds only ever **append**. Their export is the whole event every time, so a
re-run re-sends rounds already here: those come back `"skipped": true`, unread
and unchanged. A round numbered at or below the last round this event has played
is never inserted or overwritten — that would rewrite results people were told
at the table. Imported pods get no room; their games were played elsewhere.

A round whose tables all have a result lands `closed`; one still missing a
ruling lands `active`, and only the **last** round imported may be incomplete —
409 otherwise, because only one round can be open. Results are written through
the same path an organizer's ruling takes, so an imported bye scores exactly
what a bye issued here scores.

- Unknown `source` → **400** (never guessed at; the wrong reader is worse than
  no import).
- A payload the adapter will not guess at → **400** naming the round and table:
  a player with no id, a winner who is not seated, an unrecognised round label.
- A round already open here → **409** ("close the current round before
  importing").
- Ended or expired → **409**. Over 2000 entrants or 40 rounds → **400**.

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
{ "reroll": false }  → { "round": 2, "kind": "swiss", "pods": 3 }
```

- `reroll: false` with a round already active → **409**.
- `reroll: true` discards the current round's pods and re-pairs with an
  incremented seed. Only sane before play starts; the API does not stop you.
- No undropped entrants → **400**.
- **After a cut this opens the next bracket round instead** (`kind:
  "elimination"`), paired from the bracket rather than the standings. Re-roll
  in a bracket is **409**: the pairing is the seeding, so it would come back
  identical.

Pairing is deterministic given `(field, points, met, seed)`. Everything is
computed and persisted before the round is announced, so opening a round is a
broadcast of settled state rather than work done while clients poll.

Pod sizes never fall below 3 — remainders of 1–2 are absorbed into neighbours.
The one pod of one is a bracket bye (below): it has no room and its result is
written the moment the bracket is drawn.

### `POST /api/tournament/{code}/cut`  *(organizer)*
Cut the field to the top N and open the first single-elimination round.

```jsonc
{ "size": 8 }        // omit to use the size GET /{code}/plan recommends
→ { "ok": true, "cutTo": 8, "round": 6, "kind": "elimination",
    "pods": 4, "byes": 0, "remaining": 8,
    "seeds": [ {"entrantId": "…", "name": "…", "seed": 1, "points": 15} ] }
```

- **Seeding is the Swiss standings** as they stand (points, opponents' points,
  name) — the order the standings have shown all day.
- **A dropped entrant is skipped** and everyone below moves up a seat. Nobody
  is cut into a bracket they have gone home from.
- Requires a closed round to seed from → **409**; refuses over an open round →
  **409**; `size < 2` → **400**; `size` larger than the field takes the whole
  field. A structure that recommends no cut needs an explicit size → **409**.
- **Re-drawable until someone plays** (a bye is not playing): a second `cut`
  re-seeds the same round. Once a bracket pod has a result → **409**.

**Bracket rounds.** Each round pairs the survivors into pods and only the
winner of each pod goes on, so the field shrinks by a factor of about
`podSize` per round — halving it at 1v1, quartering it at four to a table.
The bracket is **fixed, not re-seeded**: pods snake across the ordered field
(1 with 8, 2 with 7, …), and after the first round the field is ordered by the
pod each player came out of, so the 1v8 winner meets the 4v5 winner whoever
those turn out to be. A remainder becomes **byes off the top** — a pod of one,
no room, `kind: "bye"`, complete on creation, scored by `settings.byeScoring`.

A pod that ends with two players sharing first has produced nobody to advance:
the next `POST /rounds` is **409** naming the table. Opening a round when one
player is left is **409** — the cut is decided; end the event.

State: `entrants.cut_seed` (bracket seed, NULL = not in the cut) and
`trounds.kind` (`swiss` | `elimination`). Everything else about the bracket is
derived from the pod results that already exist.

**Matches are a single game**, in a bracket exactly as in Swiss. A pod is one
result; there is no best-of-three model anywhere in this system and the cut
does not quietly introduce one. Running a Premier-level MTG playoff by the book
would need one, and that is an open decision, not an oversight.

### Seating overrides  *(organizer)*

The pairer seats the round; these three endpoints are the organizer's override
over it, for the late registration, the obvious mis-seat, and the table that is
being streamed and wants a name.

**They all stop at the same line: a recorded result.** A pod's result is a
ruling about a specific set of players, so moving anyone in or out of a decided
pod is **409** — their points would follow them to a table they never played
at, and `met_history` would claim they faced people they never sat with. The
route after a result is to correct the result (versioned, auditable), not to
re-pair around it. Before a result there is nothing to rewrite: `met_history`
and `standings` are both *derived* from `pod_seats`, so whoever is sitting at
the table when it is decided is who played there, and a move needs no repair.

Every one of them also requires the pod to be in the **open** round; a closed
round is **409** (`"no round is open"` / `"that table belongs to a round that is
no longer open"`).

#### `POST /api/tournament/{code}/pods/{pod_id}/move`
```jsonc
{ "entrantId": "kQ7…" }
→ { "ok": true, "moved": true, "from": 1, "to": 3, "seat": 5 }
```
The pod in the path is the **destination** — "seat them here". The table they
came from is derived from the open round, so an entrant with **no** seat in it
(someone who registered after pairing) is seated rather than moved and `from`
is `null`. Moving someone to the table they are already at returns
`moved: false` rather than an error: a double-tap is not a mistake.

The seat and the room token move with them:

- the room behind the old pod retires their player row exactly as `leave` does
  — deleted in the lobby, `left_game` mid-game with the Treachery identity
  revealed (CR 907.13) — so **the token their phone is holding stops working
  there**, and host passes to the next seat if they were hosting;
- a fresh token is issued in the new pod's room, which they pick up from their
  own `GET /{code}?token=` poll (`myPod.roomToken`). Nothing is typed at the
  table. A room token is scoped to one room; it is never carried across;
- the seats they left are renumbered 1..n so turn order has no hole in it;
- arriving into a game already under way, they start on the room's resource
  total. Nothing can deal a Treachery identity mid-game, and the room's log
  says so at the table rather than leaving them silently card-less;
- if taking them out leaves one player alone in a live game, that game ends and
  reports itself, the same as if they had left.

Size limits still apply, both ends:

| Refused | Because |
|---|---|
| destination would exceed `podSize + 1` | the pairer's own ceiling — `pod_sizes()` grows a pod by one to absorb a remainder and never further |
| source would drop below 3 | pod sizes never fall below 3 anywhere else either; move somebody in first |
| entrant has dropped | undrop them first |

#### `POST /api/tournament/{code}/pods/{pod_id}/seats`
```jsonc
{ "entrantIds": ["kQ7…", "b2R…", "…"] }   // seat 1 first
→ { "ok": true, "seats": [ … ] }
```
Sets turn order at one table, and mirrors it onto the room's seats so a table
is never shown two different orders. The list must name every player at that
pod **exactly once** — a partial order would leave duplicate or missing seat
numbers, so it is **400** and nothing changes.

This is the arranging half of `settings.seatAssignment: "manual"`; without it
that mode only ever meant "leave the pairer's order alone". Seat 1 takes the
first turn, which is a real advantage in multiplayer — this is a fairness
control, not cosmetics.

#### `POST /api/tournament/{code}/pods/{pod_id}/name`
```jsonc
{ "name": "Feature" }        // null or blank clears it
→ { "ok": true, "podId": 12, "table": 3, "name": "Feature" }
```
Pods are numbered, and the number stays the pod's identity — the name is a
label ("Feature", "Bar side"), never something anything looks up by. Max 40
characters. Two tables in one round answering to the same name (case-insensitive)
is **409**: somebody would be sent to the wrong one. The name reaches the
players through their room's tournament block as `tableName`, beside `table`.

Unlike the other two, naming is allowed on a pod in any round — it changes no
state a result depends on.

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

**In a bracket round the setting does not apply.** MTR 2.4's other half: a
single-elimination match may not end in a draw, so after the additional turns
the highest life total wins. `draw_all` has no legal outcome to produce there,
so the pod is decided by the game profile's `eliminationTimePolicy`
(`highest_life` for MTG) — official behaviour in a cut, a house rule in Swiss,
which is why it is a profile fact and not a settings key. Two exceptions, both
landing on `awaiting_result`: an organizer who chose `organizer_decides` still
rules every pod themselves, and a bracket pod **level at the top** is not
broken by seed, seat or anything else we could invent.

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
{ "kind": "placement",                 // placement | draw | bye | unfinished
  "places": [ {"entrantId": "kZ8vQ1nR", "place": 1} ],
  "note": "ruled a draw at time",
  "expectedVersion": 2 }               // optional optimistic-concurrency guard
→ { "ok": true, "version": 3 }
```

Any other `kind` → **400**. The kind decides how the pod is scored, so an
unrecognised one used to fall through to placement scoring silently: a client
forwarding another system's spelling (`"Draw"`, §9) got a win for seat one and
wrong standings with nothing to notice it by. `draw` and `bye` may be posted
with no `places` at all — every seat then shares first place.

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

A result's `source` is `auto`, `organizer` or `import`. `import` is a decision
made in another system entirely (§9) and is kept apart from `organizer` so
nobody reads a scorekeeper's ruling into a row nobody here ruled on. An
imported pod has no room, so the automatic path never reaches one.

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

Shared limiter (`limits.py`). Classification is purely method + path suffix:
every `GET` is `normal` (900 req / 60 s per client), and a write is `sensitive`
(20 / 600) only when its path ends in one of `SENSITIVE_SUFFIXES` — the list is
the contract, so read it there rather than inferring from the endpoint's
purpose. Today that is `/rooms`, `/join`, `/reclaim`, `/start`, `/rename`,
`/display`, `/lift`; on tournaments `/claim`, `/entrants` and `/turn`; and on
accounts `/signup`, `/login`, `/recover`, `/password`, `/recovery-codes`,
`/email`, `/delete`. Everything else is `normal` — life taps, results, official
calls, timer writes, notes, `/logout`. Clients are identified by a salted HMAC
of the IP — pseudonymous, never the raw address. Repeat offenders escalate
1h → 6h → 24h → 7d.

The identifier is per-IP, so a venue behind one NAT shares one bucket. That is
fine at 900/60 and tight at 20/600: ten pods counting five extra turns each is
50 `POST /turn` calls from one address, over the 20-per-10-minute limit. Nobody
has hit it in an event yet; if it bites, the fix is a per-entrant bucket for
`/turn`, not a looser limit on seat claiming.

Polling at 5 s (30 s hidden) with ~50 attendees is ~10 req/s — two orders of
magnitude inside the limit.

HTTP middleware never sees a WebSocket, so `WS /ws/{code}` checks the `socket`
bucket itself at the handshake and closes with 1013 ("try again later") rather
than accepting a socket it will not serve — the same check the room socket does.

---

## 6. Why hosting requires an email

Playing needs neither an account nor an email, anywhere in the app. Hosting
needs both: an organizer locked out mid-event strands every table, and recovery
codes are no help when they're in a drawer at home. "Accounts are optional" is
true of players and false of organizers, so the UI never says it unqualified.
It is enforced at create time (**409**), never at signup, so the requirement
lands on the person choosing to host rather than on everyone.

The address is stored plainly and is never returned by any endpoint —
`/api/account/me` exposes `hasEmail: bool`, not the value. Nor is it read for
anything else: the only code that touches the column coerces it to a bool (the
`hasEmail` flag and the hosting gate). It is collected against the day recovery
mail exists — today it recovers nothing, because the server sends no mail at
all and `/recover` authenticates on a one-time code (§10).

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

Three keys are *validated* rather than merely filtered, because falling through
to a default silently would change the event; a bad value is a **400**, never a
quiet default:

- `timeCalledPolicy` must be one the game profile offers;
- `seatAssignment` must be what `seat_pods()` implements (`random`,
  `by_standings`, `manual`) — a misspelling there would seat the field randomly
  when the organizer asked for something else, invisibly;
- `collectSanctioningId` must be `off | optional | required`, and may only be
  non-`off` for a game whose profile has a `sanctioning_account`.

One deprecated spelling survives the filter by being rewritten to its current
name before it: `collectWizardsEmail` → `collectSanctioningId`.

| Key | Read by |
|---|---|
| `scoring`, `winPoints`, `drawPoints`, `lossPoints`, `placementPoints`, `byeScoring` | `points_for`, at result-decision time |
| `podSize` | `pair_round(preferred_size=…)`, and the recommended structure |
| `seatAssignment` | `seat_pods(mode=…)`, and `pods/{id}/seats` is how `manual` is arranged |
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
`spectatorView`, `staffRoles`, `rounds`); they are marked there. The cut is now
built and still not a setting: its size is an argument to `POST /{code}/cut`
(defaulting to the structure's) and its time-called ruling is a game-profile
fact, because neither is a knob an organizer sets once at creation. Anything added
to the defaults dict must be read by something in the same change — a settings
key with no code behind it is the failure mode `AGENTS.md` names, and silent
filtering makes it invisible from the outside rather than merely inert.

## 7. Divergences from `tournament-api-design.md`

| Design | Shipped | Why |
|---|---|---|
| `GET /rounds/latest`, `/standings`, `/calls` | folded into `GET /{code}` | three polls became one snapshot; cheaper and race-free |
| `/tables/{id}` | `/pods/{pod_id}` | "pod" is the word players use |
| `WS /{code}/ws` | `WS /ws/{code}` | built after all: clock pushes over the room socket only reached players already sitting in a pod, so standings, pairings and the calls queue still waited for a poll |
| organizer secret returned once | account session + email | recoverable; a lost secret mid-event is unrecoverable |
| anonymous official calls allowed | seated entrant token required | resolving a call grants time; anonymous let a stranger aim it at any table |
| organizer-named pods, drag-to-assign | both built server-side; no drag UI yet | automated pairing landed first, but a late registration and a mis-seat both need an override — §3 *seating overrides*. The organizer UI still has no drag-to-assign control |
| — | `POST /rounds/close` | the design had no way to end a round |
| — | `entrants/{id}/release`, `/drop`, `/undrop` | mis-taps and departures both happen constantly |
| — | `GET /mine`, `GET /{code}/plan` | an organizer needs to find their own events, and to see what a field this size is usually run as |
| `structure: swiss_top_cut` as a setting | `POST /{code}/cut` | a cut is an action taken on the day with the standings in front of you, not a mode chosen before anyone has arrived |

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
| `elimination_time_policy` | how an unfinished *bracket* pod is decided at time, where a draw is not a legal outcome. Not the organizer's choice, so not a setting; `None` means the game publishes no such rule and the organizer rules |
| `sanctioning_account` | label for the id a sanctioned event collects, and the only wording the server uses for it. `None` means the game has no sanctioning body, and `collectSanctioningId` cannot be turned on |

### `GET /api/tournament/games`
```jsonc
{ "games": [ { "key": "mtg", "name": "Magic: The Gathering",
               "publisher": "Wizards of the Coast", "defaultPodSize": 4,
               "modes": ["life", "treachery"], "resource": "life",
               "resourceStart": 40, "resourceDirection": "down", "resourceGoal": 0,
               "timeCalledPolicies": [ … ], "eliminationTimePolicy": "highest_resource",
               "sanctioningAccount": "Wizards account email" } ] }
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
| `winner_id` | `pod_results.kind` + `pod_seats.place` | typed, ordered, multi-place; the wire shape is `places[]` on the result endpoint |
| — | `entrants.external_ref` | `"source:id"`, makes imports re-runnable |

**Where we deliberately differ**, and what an adapter must therefore do:

| Their shape | Adapter must | Why ours differs |
|---|---|---|
| `winner_id: "Draw"` | map to `kind: "draw"` | a magic string in an id field forces every client to special-case it |
| `winner` name beside `winner_id` | discard the name | results denormalized onto display names, which change |
| `round: "Top 8"` | map to `trounds.number` (integer) + `trounds.kind = "elimination"` | union-typed fields via magic values |
| `table: "Byes"` | map to `kind: "bye"` | same |
| single `winner` per pod | expand to `places[]` | can't express placement, survival points, or a time-called draw |

**Imports are one-way.** TopDeck's API cannot accept results, so pairings can
flow in but our results stay local. This is structural, not a policy: an adapter
has one method, `read`, and no counterpart that sends anything back. Every
import response and every row of `GET /import/sources` carries `oneWay: true`
and says it in a sentence, because a UI that offers an import without saying so
leaves organizers assuming a sync that does not exist.

**The adapter itself is a reader and nothing more.** `app/importers.py` holds
the shapes above and one implementation of them (TopDeck); it touches no
database and knows no tournament code. `POST /{code}/import` (§3) writes what an
adapter returned, in the vocabulary of this table alone. Adding a second source
means adding an adapter — if it meant editing the import endpoint, this boundary
would be in the wrong place.

Two details the table does not show:

- **"Top 8" needs both halves.** `trounds.kind = "elimination"` says the round
  is a bracket round; `entrants.cut_seed` says who is in the bracket at all,
  and it is what makes the app show a cut and pair the next round from it
  rather than from Swiss standings. An import seeds it from the order the
  source lists people in the first bracket round — that is the bracket's own
  order, and the standings behind it were computed elsewhere. It is the same
  cut `POST /{code}/cut` produces, not a second notion of one.
- **A bye is a pod of one.** Their `"Byes"` row is a list of people who sat out,
  folded into one pseudo-table because their model has nowhere else to put it.
  Ours does, so the row expands to one bye pod per player, each scored by
  `settings.byeScoring`.

---

## 10. Known gaps

- **Auto-result is test-covered, not event-proven.** The room → placement path
  has never run in a real game inside a tournament pod. Prove it with a
  throwaway 4-player event before running anything that counts.
- **The tournament WebSocket is server-side only so far.** `WS /ws/{code}`
  (§3) pushes every event-wide change, but the shipped client still polls
  (5 s foreground, 30 s hidden) and does not open the socket yet, so in the
  browser standings and roster changes still lag by up to one poll. Clock
  changes never did: they are pushed over each pod room's existing socket,
  because a pause a player cannot see is a timer that visibly keeps running.
- **The top cut has no UI.** `POST /{code}/cut` runs the cut, seeds the
  bracket and pairs single-elimination rounds (§3), but the organizer page has
  no button for it and still says the cut is not automated. Until that lands
  the feature is API-only, and no bracket is drawn on anyone's phone.
- **A bracket match is one game, not best-of-three.** Every pod in this system
  is a single result. An MTR-faithful playoff is a match of three games with
  sideboarding; modelling that is an open decision nobody has taken, and the
  cut deliberately does not fake it.
- **Final standings ignore the bracket.** `standings` stays in Swiss order
  after a cut; who won the playoff is in `cut.champion`, not at the top of the
  table. An organizer reading out final placings has to read both.
- **Manual pod assignment has no UI.** The API is complete — move, seat order,
  table name (§3 *seating overrides*) — but the organizer screen offers none of
  it, so today it is reachable only by a client that calls the endpoints
  directly. Re-roll is in the same position: in the API, no UI control.
- **The recovery email recovers nothing yet.** Hosting is gated on a stored
  address (§6), but there is no mail-sending code in the server: the only
  working recovery path is a one-time code. An organizer who loses both their
  password and their codes is not rescued by the address we made them give.
  Either wire up mail or stop calling it a recovery email.
- **Rename and export have no UI control yet.** Both endpoints are complete and
  tested (§3); the organizer screen has no rename field and no download button,
  so today they are reachable only by an API client.
- **The import has no UI.** `GET /import/sources` and `POST /{code}/import`
  are complete and tested (§3, §9), but the organizer page has no way to pick a
  source or hand over a file, so today an import is reachable only by an API
  client. Whatever lands must print the one-way sentence beside the button, not
  behind a help link.
- **No organizer-visible expiry notice.** An expired tournament reads as
  `expired` in the API and in `GET /mine`, but no UI surfaces the distinction
  from `ended` yet.

### Idle expiry

A tournament idles out after `tournaments.IDLE_TIMEOUT` (12 h — a tournament
day, not a room's 3 h) with no organizer or entrant activity, and its status
becomes `expired`. Two paths, the same shape as the room sweep: a bulk
`expire_idle_tournaments()` on `POST /api/tournament` and `GET /mine`, and a
single-row check inside `get_tournament` so any read of one stale tournament
settles it. Expiry is not a 410 — an expired event still reads, with its
standings and history intact; what it can no longer do is open a round.

Rooms belonging to a **live** tournament are exempt from the 3 h room sweep,
which is what keeps a pod alive over lunch. Live means the tournament is
neither `ended` nor `expired` **and** is itself inside its 12 h window — both
room-expiry paths (`expire_idle_rooms` and the per-room check in `get_room`)
ask that same question. So ending or expiring a tournament hands its pod rooms
back to the room sweep; nothing stays open behind an event that is over.
