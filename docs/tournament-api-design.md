# Tournament API — design

> **This is the design, not the contract.** It records what we intended before
> building, including the stress test that shaped it. The API as actually shipped
> is in [`tournament-api-contract.md`](./tournament-api-contract.md); where the two
> disagree, the contract is right. Divergences are listed there with reasoning.


*Written 2026-07-19, before the tournament layer was built. Most of it shipped;
the parts that did not are marked **not built** where they appear. Treat this as
the record of intent and the stress test behind the decisions — never as a
description of the server. That is [`tournament-api-contract.md`](./tournament-api-contract.md).*

Companion to [tournament-research.md](./tournament-research.md), which covers the
research and licensing. This document is the API and data model, plus a
deliberate stress-test of both.

---

## 1. Why this shape

TopDeck's [Tournaments V2 API](https://topdeck.gg/docs/tournaments-v2) was studied
before designing ours. Its resource hierarchy is sound and worth mirroring:

```
tournament → rounds[] → tables[] → players[]
```

A pod is a table with N players, so 1v1 is the degenerate case rather than a
separate concept. `GET /rounds/latest` is exactly what a table app needs. Copying
the skeleton costs nothing and makes an import adapter close to a field-rename.

**Deliberately not copied:**

| Their choice | Problem | Ours |
|---|---|---|
| `winner_id: "Draw"` | magic string in an ID field; every client special-cases it | typed `result.kind` |
| `winner` name beside `winner_id` | results denormalized onto display names, which change | ids are identity, names are display-only |
| `round` is a number *or* `"Top 8"`; `table` *or* `"Byes"` | union types via magic values | separate typed fields |
| single `winner` per pod | can't express placement, survival points or time-called draws | placement-based results |

**Missing from every platform, because nobody owns the table:** live state (life,
commander damage, elimination order), explicit seat/turn order, and round timers
that the players' own devices show.

## 2. Resource model

- **tournament** — code, name, organizer secret, mode (life/treachery), settings
  (pod size, starting life, rounds, scoring), status, `last_active`
- **entrant** — tournament-scoped identity: display name, random claim token,
  optional `account_id`, optional `external_ref` (for imports), `dropped_at`
- **round** — number, status, timer start/duration/pause
- **table** (pod) — round, table number, bound `room_code` + `game_no`, status
- **seat** — table, entrant, seat index (= turn order), result placement
- **result** — per table: kind, places, source, decided_at
- **official_call** — a judge call raised from a table: caller entrant,
  category, note, status (`open`/`acknowledged`/`resolved`), who claimed it and
  when, resolution note, and any time extension granted

## 3. Endpoints

```
POST   /api/tournament                      create (organizer secret returned once)
GET    /api/tournament/{code}               summary + current round
GET    /api/tournament/{code}/roster        entrants + claim state
POST   /api/tournament/{code}/claim         {entrantId} → entrant token
POST   /api/tournament/{code}/entrants      organizer: add/import
POST   /api/tournament/{code}/rounds        organizer: generate + open a round
GET    /api/tournament/{code}/rounds/latest live view: tables, seats, timer
GET    /api/tournament/{code}/rounds/{n}    historical round
POST   /api/tournament/{code}/tables/{id}/result   report or override
GET    /api/tournament/{code}/standings     points + tiebreakers
POST   /api/tournament/{code}/timer         organizer: start/pause/extend
POST   /api/tournament/{code}/tables/{id}/call     player: call an official
GET    /api/tournament/{code}/calls         staff: open + recent calls
POST   /api/tournament/{code}/calls/{id}/ack       staff: claim it ("on the way")
POST   /api/tournament/{code}/calls/{id}/resolve   staff: close, optionally +time
WS     /api/tournament/{code}/ws            tournament-level push
```

### Result object

```jsonc
{ "kind": "placement",          // placement | draw | unfinished
  "places": [ {"entrantId": 41, "place": 1, "points": 3},
              {"entrantId": 52, "place": 2, "points": 0} ],
  "source": "auto",             // auto | organizer
  "decidedAt": 1784500123,
  "note": null }                // organizer's reason when overriding
```

`source` records *how* a result was decided, so an organizer can see which pods
self-reported and which they adjudicated. Overriding is an explicit event.

---

## 4. Stress test

The design above is the easy part. What follows is what broke when it was
attacked, and the decision taken for each.

### Pairing

1. **Counts that don't divide.** 11 players is 3+4+4, not 4+4+bye. Pod sizer
   prefers 4, degrades to 3 and 5, and never leaves someone out. 5 players is one
   pod of 5, not 4+1.
2. **A pod of one is impossible.** If the remainder is 1, absorb into a pod of 5
   before ever issuing a bye. Byes exist only when the tournament has fewer
   players than a single pod.
3. **Byes still need points.** A bye scores as a win by default (configurable),
   is recorded as a table with one seat and `result.kind = "bye"`, and never
   goes to the same entrant twice while anyone else is un-byed.
4. **Repeat avoidance becomes infeasible.** In an 8-player, 4-round event
   everyone meets repeatedly. The pairer *minimizes* repeats via cost, it does
   not require zero: cost = (repeat pairs × 10) + (points spread × 1). It always
   returns a pairing; it never fails.
5. **Re-roll must differ.** Organizer re-roll increments a seed counter, so a
   second roll is a genuinely different valid pairing and the same seed always
   reproduces the same one.
6. **Drops between rounds.** `dropped_at` excludes an entrant from future
   pairings without deleting history.
7. **Drops mid-round.** The pod plays on as a 3. No re-pairing mid-round, ever —
   that would invalidate a game in progress.
8. **Late arrivals.** Entrants added after round 1 join from the next round, with
   points starting at 0 (or organizer-set catch-up points).

### Results

9. **Time called with several players alive.** Auto-detect never fires, because
   nobody was last-standing. The timer expiring flips the table to
   `awaiting_result` and applies the tournament's time-called policy (§6).
10. **Draw semantics vary by rules set, so it's a setting.** Per MTR 2.4 an
    unfinished game is a draw and life totals are *not* a tiebreaker; life only
    decides single-elimination rounds. Current cEDH practice goes further and
    gives the draw to *every* player in the pod, including those already
    eliminated. Both are supported — see §6.
11. **Concession.** Treated as elimination at that moment — it feeds the same
    elimination-order placement as dying.
12. **Placement comes from elimination order.** We already record who died and
    when; last standing is 1st, and the rest place in reverse elimination order.
    That makes auto-detect produce a *full* placement, not just a winner.
13. **Overrides need an audit trail.** A result row is versioned: overriding
    writes a new row with `source: "organizer"` and a note; the prior result is
    retained. Standings read the latest.
14. **Idempotency.** Result POSTs carry the table's expected current version;
    a stale version is rejected rather than silently overwriting a correction.
15. **Which game counts.** A table binds to `room_code` **plus `game_no`**. Rooms
    can be reopened and replayed, so without the game number a re-deal would
    silently retarget the round's result.
16. **Scoring is configurable.** Default win 3 / draw 1 / loss 0; placement
    scoring (4/3/2/1) supported since Commander leagues commonly use it.

### Identity and claiming

17. **Claim by id, never by name.** Duplicate display names are legal (we allow
    them deliberately), so the roster claim targets `entrantId`.
18. **Claims lock on first use**, with the organizer able to release one. A
    wrong-name tap is recoverable in seconds and visible in the log.
19. **Lost session.** Re-claim from the roster; a locked claim needs an organizer
    release. Same mental model as our room seat reclaim.
20. **Spectators and judges.** A tournament-level read-only view exists (roster,
    pairings, standings) with no claim — a judge shouldn't need a seat.
21. **Optional Wizards email.** Off by default, enabled per tournament by the
    organizer, stored on the *entrant* (never the account), deleted with the
    tournament. It exists only where a sanctioned event needs it.

### Rooms and lifecycle

22. **A new room per pod per round.** Membership changes every round, so reusing
    a room would muddle history. The tournament moves players: an entrant token
    is exchanged for a room player token when the round opens.
23. **Idle expiry must be tournament-aware.** Rooms currently close after 3h
    idle, which would kill pods over a lunch break. Rooms belonging to a live
    tournament inherit the tournament's clock instead.
24. **Rooms outlive the round** for history, but stop accepting play once the
    round closes.
25. **Display devices** attach per pod exactly as today; a tournament-wide
    overview display is deferred but the model doesn't preclude it.

### Calling an official

36. **One button, from the table.** Any seated player raises a call from the ⋮
    menu; it carries the table number and room code so a judge knows where to
    walk. Optional category (rules question, slow play, deck problem, other)
    and a free-text note, both skippable — someone with a problem shouldn't
    face a form.
37. **Acknowledge is a distinct step from resolve.** A judge claims the call,
    which tells the table someone is coming and stops a second judge walking to
    the same pod. Resolution is separate and can carry a note.
38. **Calls are attributed, not anonymous.** Penalty tracking and repeat-issue
    patterns need to know who called; the log records it, and the whole call
    history stays with the tournament.
39. **One open call per table.** A second tap while a call is open is a no-op
    rather than a queue of duplicates. Rate-limited like other write routes.
40. **Resolving can grant a time extension in the same action.** This is how
    judges actually work — the ruling costs the table minutes, so the extension
    belongs on the resolution, applied to that table's deadline (§ per-table
    extensions), not the round's.
41. **Unacknowledged calls escalate visually.** The staff queue sorts by age and
    flags anything waiting; a call nobody sees is worse than no button.
42. **A round can't quietly close over an open call.** Closing prompts the
    organizer to resolve or explicitly dismiss outstanding calls, so they end up
    in the record either way.
43. **The caller may drop or be eliminated.** The call survives its caller —
    it belongs to the table, not the person.

### Timer

26. **Server-authoritative.** The payload carries `endsAt` *and* the server's
    `now`, so clients compute an offset instead of trusting device clocks.
27. **Per-table extensions.** Judges extend a single pod, not the whole round —
    so the extension lives on the table, and the effective deadline is
    `round.endsAt + table.extensionSeconds`.
28. **Pause is global**, extensions are local. Both are organizer actions and
    both are logged.

### Organizer authority

29. **Losing the organizer's device must not strand an event.** The organizer
    secret can be held by more than one device, and an account-linked organizer
    can always recover. This is the strongest argument yet for accounts.
30. **Staff roles.** Judges get result entry and timer control without the
    ability to re-pair or delete. One flag now, finer permissions later.

### Scale

31. **Two push channels.** Room WebSockets already exist; a tournament-level
    channel carries roster, round and standings changes. A player's client
    subscribes to both.
32. **Round transitions are a thundering herd.** 100 clients re-route at once.
    Pairings are computed and persisted *before* the round opens, so the
    transition is a broadcast of already-written state, not 25 pod creations
    under load.
33. **Pagination.** Standings and rounds page at 200+ entrants.

### Adapters

34. **`external_ref` on entrant** (`source` + `id`) makes an import re-runnable
    without duplicating people.
35. **Imports are one-way and must say so.** TopDeck's API cannot accept results,
    so an imported tournament's pairings can flow in but our results stay local.
    The UI has to state this plainly or organizers will assume a sync that
    doesn't exist.

---

## 5. Interface language

Two rules, in order:

1. **Prefer a symbol to a sentence.** Every string is a translation liability;
   a symbol that needs no translation can't be mistranslated. Life ±, ☠, 👑, ⏱
   and ⚔ carry themselves.
2. **Where words are needed, translate them.** Icon-only interfaces trade one
   ambiguity for another — 🚩 reads as report, penalty *or* flag-for-review
   depending on who's looking. Icon plus a translated label is what actually
   removes a language barrier.

Calling an official uses a **raised hand ✋**, not a referee's shirt: striped
officiating jerseys read as "referee" mainly in North American and European
sports, whereas raising your hand is literally what a player does at a Magic
table to call a judge. The icon mirrors the physical action.

Icons are **single-colour outline SVGs stroked in `currentColor`**, never emoji.
Emoji can't be recoloured, so a theme would have no effect on them; they also
render differently per platform and several carry skin-tone or gender variants
we'd be choosing on a user's behalf.

Every icon resolves through one `<Icon>` component on a 24×24 grid, so adopting
a polished set later (Lucide, MIT; Material Symbols, Apache-2.0) touches that
file and nothing else. Colours come from CSS custom properties in `:root`, which
is what a selectable theme will swap.

Every icon-only control still carries a translated `aria-label`; a screen reader
can't infer a picture.

Translations come from people who speak the language. A machine-translated UI is
its own kind of barrier, and a wrong string under time pressure at a tournament
is worse than an English one.

## 6. Clients

**Organizer management is mobile-first** (this said desktop-first when written;
the decision was reversed once the console became section-based). Pairing review, re-rolls, result
overrides, timer control and standings all want screen area and a pointer;
cramming them into a phone would compromise the part of the product that has to
be fast under pressure at a live event. Player and display clients stay
mobile-first as they are today. Native/mobile management comes later — the API
boundary means it's a client, not a rewrite.

## 7. Settings

Everything contested is configurable rather than decided for the organizer.
Defaults follow official rules where they exist, and prevailing Commander
practice where they don't.

> **Seven of these were never built**, and are marked **not built** below. The
> shipped settings surface is the table in `tournament-api-contract.md` §6a,
> which is authoritative. This matters more than a normal doc drift: unknown
> keys are silently dropped on create, so posting one of the unbuilt settings
> returns 200 and changes nothing.

### Scoring

| Setting | Options | Default |
|---|---|---|
| `scoring` | `win_draw_loss` (3/1/0) · `placement` (4/3/2/1) | `win_draw_loss` |
| `byeScoring` | `win` · `draw` · `custom` | `win` |
| `drawPoints` | integer | 1 |

### Time called

Per MTR 2.4 the active player finishes their turn, then five additional turns
are played; if still unfinished it's a draw, and **life totals are not a Swiss
tiebreaker**. Life totals decide single-elimination only. cEDH events commonly
extend the turn instead of counting turns.

| Setting | Options | Default |
|---|---|---|
| `timeCalledPolicy` | `draw_survivors` · `draw_all` (cEDH: eliminated players share it) · `highest_life` · `organizer_decides` | `draw_all` |
| `extraTurns` | integer (MTR: 5) · `0` to disable | 5 |
| `turnExtensionMinutes` — **not built** | integer · `0` to disable | 0 |
| `topCutPolicy` — **not built**, no cut is performed | `highest_life` (MTR single-elim) · `organizer_decides` | `highest_life` |

`highest_life` reads the life totals the table is already tracking, which is the
one place our owning the table pays off directly for adjudication.

### Structure

| Setting | Options | Default |
|---|---|---|
| `structure` | `swiss` · `swiss_top_cut` | `swiss` |
| `topCutSize` — **not built**; cut size comes from the game profile's bracket | 4 · 8 · 16 | 4 |
| `podSize` | 3 · 4 · 5 (preferred; sizer degrades as needed) | 4 |
| `rounds` — **not built**; round count is advisory from `GET /{code}/plan` and configures nothing | integer · `auto` (by entrant count) | `auto` |

### Seating

| Setting | Options | Default |
|---|---|---|
| `seatAssignment` | `random` · `by_standings` (leader seats first) · `manual` | `random` |

Seat order is turn order, and turn order is a real advantage in multiplayer, so
this is a genuine fairness knob rather than cosmetics.

### Access

| Setting | Options | Default |
|---|---|---|
| `organizerAuth` — **not built, and the choice was removed**: hosting always requires an account with a recovery email | `secret` (device-held) · `account` (recoverable, multi-device) | — |
| `collectWizardsEmail` | `off` · `optional` · `required` | `off` |
| `spectatorView` — **not built**; the roster is public to anyone holding the code | `public` · `code_only` · `off` | `code_only` |
| `staffRoles` — **not built**; every staff action requires the owning organizer's session | `off` · `judges` (result entry, timer, official calls; no re-pairing or deletion) | `judges` |
| `allowOfficialCalls` | `on` · `off` (small leagues with no judge) | `on` |

## 8. Still open

- Whether `rounds: auto` uses the usual Swiss table (log2 of entrants) or a
  Commander-specific curve — worth checking against real event structures.
- Whether top cut re-pods by standings or by bracket seeding.
