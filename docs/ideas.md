# Ideas — not a roadmap

A parking lot. Nothing here is scheduled, committed to, or designed. Items get
written down when they come up so the thinking isn't lost, and so the
constraints that would shape them are recorded while they're fresh.

If something here graduates, it gets its own design doc and moves out.

---

## Paid registration through a payment processor

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

**Merchant of record is the big fork**, and it should be decided before any
code:

- *Organizer is the merchant* — money goes to their PayPal, we only orchestrate.
  Simple. They own refunds, chargebacks, tax and their own compliance.
- *We collect and disburse* — we hold other people's money, which is a different
  legal animal (money transmission licensing in the US, per state). Substantially
  heavier, and the reason most small platforms pick the first option.

Almost certainly the first, but write it down as a decision rather than
drifting into the second by accident.

**This inverts the app's privacy stance, and that's the real cost.** Everything
so far is built on collecting as little as possible: no email required, no IP
ever associated with a user, salted hashes for rate limiting, a game history
carrying nothing but user id and name. Payment brings names, emails, a payment
relationship, and — because of refunds, chargebacks and disputes — a *retention
requirement* that directly contradicts "keep no identifiers." That's not a
blocker, but it means paid events are a distinct data regime, and the honest
approach is to keep it that way: an account that never registers for a paid
event should never acquire any of it.

**Money changes the licensing question.** The Wizards Fan Content Policy is
noncommercial. Charging for tournament use was already flagged in the roadmap as
needing an answer; a payment portal makes that question load-bearing rather than
theoretical. The distinction between pass-through entry fees an organizer would
have charged anyway and revenue we take is likely to matter.

**Then the ordinary hard parts:** refunds and cancellation windows, no-shows,
capacity limits and waitlists, partial refunds when an event is cut short,
whether a dropped player is owed anything, and reconciling "paid" against
"actually turned up".

---

## Event directory

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

- **Import adapter** for TopDeck and similar. Groundwork exists
  (`entrants.external_ref`, the mapping table in the API contract); the adapter
  itself is unwritten. Imports are one-way — their API can't accept results —
  and any UI must say so or organizers will assume a sync that doesn't exist.
- **Top cut execution.** Presets recommend a cut; nothing performs one. Needs
  re-podding, bracket seeding, and single-elimination rules (where highest life
  *does* decide at time, unlike Swiss).
- **`/openapi.json` and `/docs` are public** on production, enumerating every
  route and schema on an otherwise hardened box.
- **Entrant tokens ride in query strings**, so the reverse proxy strips query
  params from access logs. That coupling isn't obvious from either file; a
  header would remove the dependency.
