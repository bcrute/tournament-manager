# Ideas — not a roadmap

A parking lot. Nothing here is scheduled, committed to, or designed. Items get
written down when they come up so the thinking isn't lost, and so the
constraints that would shape them are recorded while they're fresh.

If something here graduates, it gets its own design doc and moves out.

---

## Paid registration through a payment processor

> **Superseded 2026-07-20** by the separate events-platform project (§9 there),
> which splits participant payments into three tiers and separates them from
> subscription billing. The conclusions below survive and are load-bearing
> there — never hold money, never touch card data, containment rather than
> compromise — but the single-adapter shape does not. Kept for the reasoning.

*Noted 2026-07-19.*

Players already hand the organizer their details and money to register. The app
could take that: a player registers and pays for an event in-app, with all card
handling offloaded to the processor. **Processor behind an adapter, starting
with PayPal** — same shape as the game profiles: one interface, one
implementation to begin with, no assumption that it's the only one.

### Things that would shape the design

**Never touch card data.** Hosted checkout (redirect or the processor's JS SDK)
keeps us almost entirely out of PCI DSS scope. The moment card details cross our
server, the compliance burden changes category. The adapter interface should
make the card-handling path physically impossible to implement wrongly — it
deals in "create a payment intent, hand back a redirect URL, verify a webhook",
never in numbers.

**We never hold money. Decided.** The organizer is the merchant of record —
funds go to their processor account, and we only facilitate collection. We
orchestrate a payment and hear back whether it succeeded; we never take custody
of anyone's money.

That rules out being a money transmitter, which would mean per-state licensing
in the US, and it puts refunds, chargebacks, tax and the organizer's own
compliance where they belong: with the organizer. Any future feature that would
route funds through us — holding fees, splitting revenue, paying out prizes —
is a different product with a different legal posture, not an increment on this
one.

**Paid registration is a separate data regime, and must not leak into the rest.**
Everything so far collects as little as possible: no email required, no IP ever
associated with a user, salted hashes for rate limiting, a game history carrying
nothing but user id and name. Payment brings names, emails, a payment
relationship and — through refunds, chargebacks and disputes — a *retention
requirement* that directly contradicts "keep no identifiers."

The resolution is containment, not compromise. Whatever a paid registration
requires stays attached to that registration. **An account that never registers
for a paid event never acquires any of it, and playing without an account stays
a first-class path** (see "Identity" below). If a design ever requires an
account to play, the design is wrong.

**Money changes the licensing question.** The Wizards Fan Content Policy is
noncommercial. Charging for tournament use is already flagged in
`commercial-position.md` as needing an answer; a payment portal makes that
question load-bearing rather than theoretical. The distinction between pass-through entry fees an organizer would
have charged anyway and revenue we take is likely to matter.

**Then the ordinary hard parts:** refunds and cancellation windows, no-shows,
capacity limits and waitlists, partial refunds when an event is cut short,
whether a dropped player is owed anything, and reconciling "paid" against
"actually turned up".

---

## Identity — settled, and not up for erosion

*Noted 2026-07-19. This is current behaviour, not a future idea, recorded here
because the features above are the ones most likely to erode it.*

- **Playing never requires an account.** Anonymous is a first-class path, not a
  degraded one.
- **Accounts, display names, emails are all voluntary.** The one exception is
  hosting, which needs a confirmed recovery email, because an organizer locked out
  mid-event strands every table.
- **A tournament hands out its own temporary id.** Claiming a spot returns an
  entrant token scoped to that tournament. Being signed in does not change what
  the tournament learns about you — the entrant is that token, not an account.

`entrants.account_id` exists but is never written. That is deliberate: it is the
hook for a *voluntary, opt-in* link, and it must never be populated as a side
effect of being signed in while claiming. Three tests in
`TestIdentityStaysSeparate` pin this — claiming works with no account, claiming
while signed in leaves the link empty, and the roster exposes no account at all.

The one path that will write it is the deliberate upgrade described below, and
it stays subject to the rules above: the organizer never sees an account, and
deleting an account drops the pointer without touching the entrant row or its
results, so an event's standings can't develop holes because someone deleted
their account on the train home.

---

## Everything reasonable is an adapter

*Architectural principle, noted 2026-07-19.*

Where an external system, a game, or a vendor could plausibly be swapped, it
goes behind an interface with one implementation to start. The point isn't
speculative generality — it's that the first implementation stops being load
bearing, and its assumptions stop leaking into the core.

| Boundary | Status |
|---|---|
| Game rules and vocabulary | **Done** — `GameProfile` in `games.py`; MTG is a profile, not the base |
| Event structure | **Done** — presets carrying their own provenance |
| Payment processor | Planned — PayPal first, never card data, never custody |
| Tournament import | **Done** — `ImportAdapter` in `importers.py`; TopDeck is an adapter, not the core |
| Notification/delivery | Not needed yet |

The test of a good boundary here is the one already written down for games: if
adding a second implementation means editing the core, the boundary is in the
wrong place.

---

## Account upgrade after claiming a spot

*Discussed 2026-07-19. Approach settled; not built.*

A player claims a spot anonymously, then decides they want an account. Their
tournament identity carries over, and the organizer never sees a thing change.

**The design: entrant ids are permanent and the account holds a pointer.**
One column, written once, on a deliberate opt-in. Nothing is rewritten and
nothing has to be resolved through an alias. The upgrade also links that
entrant's `players` rows in the pod rooms in the same transaction — without
that, the new account knows the user entered a tournament but shows no games,
because history reads `players.account_id`.

### Why not promote the entrant id into the user id

This was the first instinct and it's worth recording why it was dropped, so it
doesn't get re-proposed:

- **It works exactly once.** One account plays many tournaments, and each event
  has the organizer creating its own participant row. Thirteen events, thirteen
  entrant rows, one person — they can't all share an id unless the key becomes
  `(tournament_code, entrant_id)`, at which point the entrant id isn't globally
  unique and can't be a user id anyway. So a pointer is needed for every event
  after the first regardless, and once you're keeping it, promotion buys
  nothing.
- **The rewrite is a live migration at a table.** Replacing an id mid-event
  means updating `pod_seats`, `official_calls` and results while the organizer's
  console and every player's phone hold ids they fetched seconds ago —
  triggered by someone tapping "sign in" during a round.
- **Supersession chains accumulate.** "X superseded Y" means every reader that
  touches an entrant id must know to follow an alias. Cheap to write, expensive
  to live with: standings look right for a year until one query forgets.

The user-facing promise — "my spot became my account" — is identical either
way, because a user never sees an id in either model.

### Still to decide

- **Signing in to an *existing* account after claiming.** Clean when the account
  is new; awkward when that account is already linked to a different entrant in
  the same tournament — someone claiming two spots, or a shared device.
  Recommendation is one account per tournament with a clear refusal on the
  second attempt, but that is a decision, not an edge case to discover in
  production.
- **What the prompt says.** Linking adds a durable record tying a person to an
  event, invisible to the organizer but real. The wording should say that
  plainly rather than "save your results", and must never be pre-ticked.

### Test implication

`TestIdentityStaysSeparate` stays as-is: claiming while signed in must still
never auto-link. The invariant is "never as a side effect", not "never" — a
deliberate upgrade is a separate path and needs its own tests.

---

## Event directory

> **Folded into the separate events-platform project** (§3 there) as the
> directory surface, where events are the base object rather than tournaments.
> The two constraints below — venue-centred rather than device location, and
> verification before public listings — carried over unchanged.

*Noted 2026-07-19.*

Organizers publish events under a shop or venue name. Players log in, see
what's happening nearby, and register — potentially well in advance.

**Early-bird pricing** falls out of this: an organizer offers a lower price for
registering ahead of time. Mechanically it's time-based price tiers on an event,
which is worth modelling as tiers from the start rather than as a special case,
because "member price", "student price" and "same-day price" are the same shape.

### Things that would shape the design

**"Nearby" must not mean tracking players.** Location is explicitly excluded
from what this app collects. A venue-centred directory gets the same result
without it: organizers have a fixed location, players browse or follow a region
or a specific shop, and the app never asks a device where it is. Search by
place, not geolocation by default — and if device location is ever offered, it's
opt-in, per-search, and never stored.

**A published event is a new public surface.** Everything public today is
scoped to someone holding a tournament code. A directory is world-readable by
design, which brings scraping, spam listings, and fake events by whoever can
make an account. Organizer verification, or at least a claimed-venue concept,
probably has to exist before listings are public.

**It changes the shape of the data.** Tournaments are currently ephemeral —
they idle out. A directory implies durable organizers, venues, recurring events
and schedules, which is a bigger model than "a code someone shares at a table".

---

## Smaller notes

- ~~**Import adapter** for TopDeck and similar.~~ **Built.** `POST
  /{code}/import` reads a source's export through an adapter (`importers.py`)
  and writes entrants, rounds, pods and results; the four places their shape
  isn't ours — one winner, a draw in an id field, a "Byes" pseudo-table, "Top
  8" as a round number — die at that boundary. One-way is structural: an
  adapter has `read` and no counterpart, and every response says so. What is
  left is the UI, which must print that sentence beside the button.
- ~~**Top cut execution.**~~ **Built.** `POST /{code}/cut` seeds a bracket from
  the standings and pairs single-elimination rounds, and a bracket pod at time
  is ranked on life because MTR 2.4 forbids a draw there. Two things are still
  open: the organizer page has no button for it, and a bracket match is one
  game rather than best-of-three.
- **Manual pod assignment.** An organizer cannot move an entrant between pods
  or name a table. Planned first, overtaken by the pairer, never built.
- ~~`/openapi.json` and `/docs` are public.~~ **Fixed.** Both, plus `/redoc`,
  are off unless `TABLE_DEV_DOCS=on`.
- ~~Entrant ids are sequential and semi-public.~~ **Fixed 2026-07-19.**
  `entrants.public_id` is a random string and is the only id on the wire; the
  integer primary key stays internal.
- **Entrant tokens ride in query strings**, so the reverse proxy strips query
  params from access logs. That coupling isn't obvious from either file; a
  header would remove the dependency.
