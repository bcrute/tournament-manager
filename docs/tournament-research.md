# Tournaments — research and decisions taken

*Was `tournaments-roadmap.md`. The phase plan it carried is finished or
superseded and has been removed; what remains is the research that shaped the
design and the decisions that came out of it, which are still load-bearing.*

**Remaining work is not here.** It lives in
[`tournament-api-contract.md` §10](./tournament-api-contract.md#10-known-gaps),
next to the API it concerns, so there is one list rather than two that drift.
Unscheduled ideas are in [`ideas.md`](./ideas.md); the commercial case is in
[`commercial-position.md`](./commercial-position.md).

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

**Design consequence, and it held:** pod assignment and pairings are ours.
`pairing.py` is native, deterministic given `(entrants, history, seed)`, and
depends on nothing upstream. Any third-party integration is a convenience,
never a dependency.

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
  a real question if this ever becomes commercial
  ([`commercial-position.md`](./commercial-position.md)).

**Shipped:** the disclaimer is in `FanContentNotice.tsx`, rendered in the site
footer and on the table landing and dashboard. It is reproduced verbatim with
`[Title]` resolved to "Table" — if the product is ever renamed, that string
changes with it.

### Scryfall — *removed, and this is why it stays removed*

The `/api/random-card` proxy was removed on 2026-07-18. The app now ships **no
third-party card data at all**, which sidesteps this entire licence chain —
and, as a side effect, the "no third-party requests" privacy claim in
`security.md`. `test_main.py` pins the route as gone.

Kept here because the terms explain why a commercial tier cannot re-add it, and
why "just call Scryfall for X" should be refused rather than reconsidered:

<https://scryfall.com/docs/api>

- Free, under the Fan Content Policy, for "creating additional Magic software"
  — and therefore noncommercial, which is the binding constraint.
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
all 62 scans in `frontend/public/cards/trd/`.

**Shipped:** the card JSON's `artist` field is served by the API and displayed
in the room, and the notice credits the Treachery project. Getting the
maintainers' explicit permission is still worth doing and has not been done.

### Other publishers — naming a game we don't license

Added 2026-07-27, when Lorcana became the second game profile.

Wizards is the unusual case: it publishes a Fan Content Policy, so the MTG
surface rests on an actual (if software-shaped-hole) grant. **Ravensburger
publishes no equivalent for Lorcana, and Disney IP is enforced hard.** There is
no licence to rely on, so the position has to be that we never needed one:

- **We ship no assets.** No card data, no art, no symbols, no logos, no trade
  dress. The Lorcana profile is six numbers and a Swiss table we wrote
  ourselves — `resource="lore"`, up, to 20, two to a table.
- **The name is used nominatively**, to say which game the tool suits. That is
  the same use a dice bag makes of "d20"; it is not branding, and nothing in
  the app claims endorsement or affiliation.
- **Our structures are marked unofficial.** `LORCANA_SWISS.official is False`,
  and a test asserts it, because presenting numbers we invented as a
  publisher's rules would be the actual misrepresentation.
- **Rules aren't copyrightable; their expression is.** We cite documents rather
  than reproduce them (see `MTR_PREMIER.source`), and for Lorcana we cite
  nothing because we're claiming nothing.

**The risk, stated plainly:** this is thinner ground than the MTG profile, and
the mitigation is that the exposure is small and reversible — a name in a
dropdown is a one-line revert if Ravensburger ever objects. Accepted knowingly
on 2026-07-27 for a free, noncommercial tool.

**This is the assumption that breaks first if money is ever involved.** The
Wizards policy is noncommercial outright ([`commercial-position.md`](./commercial-position.md)),
and nominative use gets read less charitably when there's revenue behind it.
A paid tier needs a lawyer, not this document.

### Third-party tournament platforms (optional interop)

| Platform | Access | Fit |
|---|---|---|
| [TopDeck.gg](https://topdeck.gg/docs/tournaments-v2) | Free API key; 100 req/min read | Read standings/decklists; create tournament needs paid sub; register players needs admin. **Cannot create rounds, pairings or seatings.** |
| [Melee.gg](https://help.melee.gg/docs/api-use/) | Organisations/staff only, granted by email | Not viable for a private group |

No adapter is written. The data model is ready for one —
`tournament-api-contract.md` §9 has the field mapping.

---

## 3. Design consequence: a pod is just a room

Recorded because it is the decision the whole tournament layer rests on, and
it is invisible from the code unless you already know to look for it.

Rooms already provide life tracking, Treachery dealing, seat order, reclaim,
history and the shared display. Tournaments are an **orchestration layer above
them**, and the dependency runs one way only: `table.py` must keep working with
no tournament in sight, reaching tournaments only through
`report_tournament_result` and the read-only clock context.

Two things follow that would otherwise look arbitrary:

- **A new room per pod per round.** Membership changes every round, so reusing
  a room would muddle history. The tournament moves players by exchanging an
  entrant token for a room player token when the round opens.
- **A pod binds to `room_code` *plus* `game_no`.** Rooms can be reopened and
  replayed; without the game number a re-deal would silently retarget the
  round's recorded result.

---

## 4. Decisions taken

These were the four open questions before the tournament layer was built. All
four are resolved, and the reasoning is kept because each one has a cheaper
wrong answer that will otherwise be re-proposed.

**1. Organizer authority — accounts, not a device-held secret.**
The cheap answer was an organizer secret in localStorage. It lost: a lost
secret mid-event is unrecoverable and strands every table. `require_organizer`
matches the session account against `tournaments.organizer_account_id`, which
is `NOT NULL`. This is also why creating a tournament requires an account with
a recovery email and returns **409** without one — the requirement lands on the
person choosing to host rather than on everyone. The designed `organizerAuth`
setting offering both modes was dropped rather than built.

**2. Room lifetime — exemption, not a second clock.**
Rooms idle out after 3 h, which would kill pods over a lunch break. The
resolution is that a room referenced by a `pods` row skips the idle check
entirely, so tournament rooms simply do not expire. Note the consequence,
recorded as a gap in the contract: **nothing expires the tournament itself.**

**3. Reclaim across rooms — solved by the entrant token.**
`pod_seats.room_token` holds each entrant's per-room token, handed back in
tournament state, so a dropped player re-enters the *right* pod without typing
a code. This is what makes "players never type a second code" true across
rounds, not just at the start.

**4. Pod size — configurable per tournament, defaulted by the game profile.**
Not fixed at four. The sizer prefers the configured size and degrades to 3 or 5
rather than ever seating someone alone; 11 players is 3+4+4, never a bye. Byes
exist only when the field is smaller than a single pod.

---

## 5. What was planned and deliberately not built

Recorded so it is not mistaken for an oversight, and so the reasoning survives:

- **Manual pod assignment and organizer-named pods.** Planned as the first
  phase, on the assumption that automated pairing was the harder second step.
  The pairer landed first and covered the need, so drag-to-assign was never
  built and pods are numbered, not named. It remains a genuine gap for an
  organizer who wants to seat a specific table by hand — tracked in the
  contract's known gaps, not here.
- **A tournament-wide display.** Deferred at design time and still deferred.
  The per-room display is unaffected; the data model does not preclude it.
- **A tournament WebSocket.** Polling proved sufficient at this scale and costs
  nothing idle. The one case that could not tolerate a poll delay — a paused
  clock still visibly running on a player's phone — is pushed over the room's
  existing socket instead.
