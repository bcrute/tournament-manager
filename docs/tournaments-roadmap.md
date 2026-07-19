# Tournaments — research & roadmap

*Written 2026-07-18. Planning only; nothing here is implemented.*

Goal: let an organizer run a tournament that spans several rooms, moving players
between rooms round by round. This document records what was researched about
official Magic APIs (because the answer shapes the design), then the plan.

Sections 6–8 cover the commercial case: what already exists, where the actual
gap is, and the content rules a paid tier would have to live by.

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

### Phase 4 — TopDeck.gg integration

Promoted from "optional" — see §7, it is close to the core thesis. Import a
roster from a TopDeck event, and report pod results back. Their read API is
free (100 req/min); creating tournaments needs a paid TopDeck subscription, so
the likely shape is: they own pairings and standings, we own the table.
Everything still works standalone if the integration is off. Melee remains out
of reach without a registered organisation.

### Phase 5 — Tournament display

Deferred deliberately.

---

## 6. What already exists (competitive landscape, July 2026)

Researched before planning a paid tier. The honest summary: **the incumbents
are good**, and neither "another life counter" nor "another pairing engine" is
a business.

### Organizer side — well served

| Tool | Notes |
|---|---|
| [TopDeck.gg](https://topdeck.gg/help/running-commander-tournament) | The default for Commander. Proprietary "Swiss Pods" pairing that converts to a circular system in later rounds so top tables can't intentionally draw into the cut; deliberate re-pair avoidance. Decklists, brackets, public event pages, Discord bot, free API, event discovery. |
| [Command Tower](https://outsidetheasylum.blog/surviving-cedh/) | Polished, cEDH-focused. Online pairings, seating order (seat 1 goes first), imports, decklist submission. Closed-source algorithm; manual pairings arrived late. |
| [MTG Event](https://www.mtgevent.com/mtg-tournament-software/) | Free. Pods, pairings, results, tiebreakers. |
| Melee / EventLink | Big events and sanctioned store play. Both gated. |

### Player side — commoditized

[Draftsim lists eleven life counters](https://draftsim.com/best-mtg-life-counter-app/).
Lifetap is full-featured, free, no ads. Playgroup adds ELO via playgroup.gg.
Lifelinker rides the Command Zone audience. There is no money in life counting.

### The one weak incumbent

Wizards' own Companion app reviews poorly — [complaints](https://justuseapp.com/en/app/1455161962/magic-the-gathering-companion/reviews)
about search, being unable to drop from events, and no tournament history — but
it is free and bundled with sanctioned play. Not a distribution fight worth
picking.

## 7. Where the actual gap is

**The seam between the organizer tool and the table.** Today an organizer runs
TopDeck, players run Lifetap, and somebody retypes results into the organizer
tool afterwards. Nothing spans that boundary.

This app already owns the table half — live life totals, shared display, seat
order matched to the physical table, and **automatic last-player-standing
detection**, which is exactly the event a tournament needs reported. "The pod
reports its own result" is the differentiator; neither incumbent can do it
alone.

Strategic consequence: **integrate rather than compete.** TopDeck has solved
multiplayer Swiss and owns event discovery; its weakness is that it stops at
the table's edge. Being the table layer that feeds it beats trying to out-pair
them.

Monetization shape, if it ever goes there: **players free** (needed for the
network effect), **organizers or stores pay**. Same shape TopDeck uses.

## 8. Rules for a commercial tier

The binding constraint is subtle and it is worth writing down:

> Scryfall grants its data **under the Wizards Fan Content Policy**, and that
> policy is **noncommercial**.

So a paid product cannot use Scryfall, and realistically cannot display Magic
card imagery or text at all without a licence Wizards does not hand out.

Fortunately nothing valuable needs it — life totals, damage-by-source, pods,
rounds, standings, seating and results require zero card content.

**The line to hold:**

1. **Commercial core ships no Magic content whatsoever.** No Scryfall calls, no
   card images, no card text, no Magic branding in the product identity.
   Mechanics are unprotectable, so generic modes ("source-directed damage",
   "hidden roles") are entirely ours to sell.
2. **Treachery never ships in a paid tier.** It stays in the free fan build, or
   arrives as a pack the user imports themselves. Getting the Treachery
   maintainers' permission is still worth doing — it settles the free build and
   the artist-credit question — but it does not make the cards commercially
   shippable, because the art belongs to third-party illustrators and the text
   is Magic-derivative.
3. **A "user-generated plugin" shield does not work if we write the plugin.**
   DMCA §512 protects material stored at the direction of *users*; the operator
   uploading it defeats the knowledge requirement, and direct liability attaches
   to the person who uploads regardless of what entity owns the platform.
4. **Draw the boundary now, cheaply.** Neutral naming in schema and UI, and the
   hidden-role engine parameterized on a role pack rather than assuming
   `data/treachery-cards.json`. `distribution()` is already pure math and the
   cards are already a data file, so this is a refactor, not a rewrite.

If money ever actually changes hands, buy an hour of an IP attorney's time.
Everything above is reasoning from published policies, not legal advice.

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
