# Tournaments — research & roadmap

*Written 2026-07-18. Planning only; nothing here is implemented.*

Goal: let an organizer run a tournament that spans several rooms, moving players
between rooms round by round. This document records what was researched about
official Magic APIs (because the answer shapes the design), then the plan.

---

## 1. Is there an official Wizards API?

**No — and not one that could serve this use case.**

| Thing | Status |
|---|---|
| Gatherer (WotC's own card database) | No programmatic access of any kind |
| EventLink (WotC tournament tool) | No public API; gated to WPN-enrolled stores |
| Magic Companion (player pairings app) | Closed; talks only to EventLink |
| magicthegathering.io, Scryfall, MTGJSON | Community projects, not official |

Two pieces of corroborating evidence that EventLink has no API rather than an
undocumented one:

- TopDeck.gg built an ["Event Link Export System"](https://topdeck.gg/blog/event-link-export-system-20250724) —
  a one-click bridge — instead of a normal integration.
- Organizers have [publicly asked Wizards for such an API since 2021](https://x.com/CubeApril/status/1403062626511429640)
  and none has appeared.

**Design consequence: pod assignment and pairings must be ours.** No upstream
API will do it, so the tournament layer is built natively and any third-party
integration is a convenience, never a dependency.

## 2. Licensing

### Wizards Fan Content Policy

<https://company.wizards.com/en/legal/fancontentpolicy> — the only licence
available to us for Wizards IP.

- **Noncommercial only.** "You can't sell or license your Fan Content to any
  third parties for any type of compensation." Ads, sponsorship and donations
  are explicitly permitted.
- **Required disclaimer, verbatim:** "[Title] is unofficial Fan Content
  permitted under the Fan Content Policy. Not approved/endorsed by Wizards.
  Portions of the materials used are property of Wizards of the Coast.
  ©Wizards of the Coast LLC."
- No Wizards logos, trademarks or patented game mechanics in branding without
  written permission.
- **Caveat worth knowing:** the policy's examples list "fan art, videos,
  podcasts, blogs, websites, streaming content, tattoos" — *software is not
  listed*. Scryfall, EDHREC et al. operate under it by convention and
  tolerance, not explicit permission. Acceptable risk for a free private tool;
  a real question if this ever becomes commercial.

### Scryfall (used today by `/api/random-card`)

<https://scryfall.com/docs/api>

- Free, under the Fan Content Policy, for "creating additional Magic software".
- **Requires** a `User-Agent` *and* `Accept` header on every request; the docs
  say do not let the HTTP library pick the User-Agent.
- Hard rate limits: `/cards/random`, `/cards/search`, `/cards/named`,
  `/cards/collection` are **2 req/sec**; everything else 10 req/sec. HTTP 429
  locks access for 30s; persistent overage can mean a permanent ban.
- Cache for at least 24h; use bulk data files for anything high-volume.
- Must not paywall the data, must not repackage without adding value, must not
  "use Scryfall data to create new games".
- Images: don't crop/alter/watermark; keep artist and copyright legible.

### Treachery identity cards

<https://mtgtreachery.net/en/> states the identity artwork is "owned by their
illustrators… taken from various websites and properly credited". We self-host
all 62 scans in `frontend/public/cards/trd/`. The card JSON carries an `artist`
field that we currently never display — see Phase 0.

### Third-party tournament platforms (optional interop)

| Platform | Access | Fit |
|---|---|---|
| [TopDeck.gg](https://topdeck.gg/docs/tournaments-v2) | Free API key; 100 req/min read | Read standings/decklists; create tournament needs paid sub; register players needs admin. **Cannot create rounds, pairings or seatings.** |
| [Melee.gg](https://help.melee.gg/docs/api-use/) | Organisations/staff only, granted by email | Not viable for a private group |

---

## 3. Design

A **pod is just a room**. Rooms already provide life tracking, Treachery
dealing, seat order, reclaim, history and the shared display. Tournaments are an
orchestration layer above them.

### Model

- **tournament** — code, name, organizer secret, game mode, settings (pod size,
  starting life, round count), status, `last_active`
- **entrant** — tournament-scoped identity with its own token; this is what
  persists *across* rooms, unlike the per-room player token
- **round** → **pods**, each owning a room (code + organizer-set display name
  such as "Pod A" or "Table 3")
- **assignment** — entrant ↔ pod, per round

### Flow

Organizer creates a tournament and shares one code/QR. Entrants join a waiting
lobby. The organizer names pods and assigns people, then starts the round: rooms
are created and every client is routed into its pod automatically.

**Players never type a second code.** The client holds the entrant token,
watches tournament state, and follows its assignment each round — reusing the
session machinery that already survives deploys and reconnects.

---

## 4. Phases

### Phase 0 — Compliance cleanup (independent of tournaments; do first)

1. Send a proper `User-Agent` and `Accept` header from the Scryfall proxy; add
   caching and a rate guard (that endpoint is capped at 2 req/sec).
2. Add the required Fan Content disclaimer to the site footer.
3. Credit Treachery card artists (the data already has the field).

### Phase 1 — Tournament shell, manual assignment

Tournament create/join, entrant identity, organizer-named pods, drag-to-assign
(reuse the display's swap interaction), start round → rooms created and players
auto-routed. Manual result entry. Basic standings.

### Phase 2 — Automated assignment

- Round 1 random, seeded and reproducible.
- Later rounds: multiplayer Swiss — group by points, minimise repeat opponents
  (greedy seeding plus local swap search is plenty at this scale).
- Awkward counts handled properly: 11 players is 3+4+4, never a bye.
- Organizer keeps re-roll and hand-edit before locking a round.

### Phase 3 — Results and standings

Pods largely report themselves: the app already detects last-player-standing and
ends games. Organizer override for concessions, draws and time limits.
Configurable scoring (default win 3 / draw 1 / loss 0), tiebreakers, CSV/JSON
export. Tournament history reuses the per-room event log, which already carries
no PII beyond names and random ids.

### Phase 4 — Optional integrations

TopDeck.gg only: import a roster, optionally push final standings. Never a
dependency. Melee is out of reach without a registered organisation.

### Phase 5 — Tournament display

Deferred deliberately.

---

## 5. Decisions needed before Phase 1

1. **Organizer authority.** Today, knowing a code *is* the credential. A
   tournament needs more — anyone with the code shouldn't re-pair round 3. An
   organizer secret in localStorage is the cheap answer; this is also the point
   where optional accounts start paying for themselves.
2. **Room lifetime vs tournament length.** Rooms close after 3h idle
   (`TABLE_IDLE_TIMEOUT`). A day-long tournament needs tournament-aware expiry
   or between-round gaps will quietly kill pods.
3. **Reclaim across rooms.** Seat reclaim is per-room today; with a tournament
   identity a dropped player should be restorable to the *right pod* from the
   tournament code.
4. **Pod size and format** — fixed 4-player pods, or configurable per round?
