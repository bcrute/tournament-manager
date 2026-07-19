# Working on this project

## Security

Everything you need is in this repo — [`docs/security.md`](docs/security.md)
holds the threat model, the decisions and their rationale, and the gaps that
are knowingly accepted. Read it before adding anything that collects data, adds
a credential, or crosses a trust boundary.

The baseline these were derived from lives at
`ssh://git@192.168.30.4:2222/ben/security-docs.git`. You do **not** need it
checked out; consult it only when starting something this project has no
precedent for.

### The rules, in full

These apply to every change here. They are not a summary of something you must
go and read — this is the whole list.

- **Deny by default.** A permission not explicitly granted is denied. An
  endpoint with no authorization check is a bug, not an oversight.
- **Never trust the client.** UI restrictions are not access control. Every
  check happens server-side, at the boundary that owns the data.
- **An id from the client is not a credential.** Resolve it through something
  the caller has already proven they may access. This project shipped five
  authorization defects from treating `pod_id` as self-authorizing.
- **Collect the minimum.** Playing requires no account and no personal data.
  That is the central design decision; do not erode it.
- **No silent failures.** A control that fails open is worse than none, because
  it produces false confidence.
- **Log the decision, not the secret.** Never log tokens, passwords, recovery
  codes, or raw IPs.

### For you specifically, as an agent

- **Do not claim a control exists until you have verified it.** `advance_turn`
  shipped with a docstring describing an authorization check it did not
  perform. A comment is not a control.
- **A settings flag that promises behaviour must implement it.** This project
  shipped three that were read by nothing (`timeCalledPolicy`,
  `collectWizardsEmail`, and a status that could never be reached).
- **Do not invent a citation.** Standards, control IDs, and tournament rules
  must be ones you have actually read. See `docs/tournament-api-contract.md`
  for how rules citations are handled.
- **Surface the tradeoff instead of quietly taking it.** Say the secure option
  costs something and let a human choose.
- **Reporting a gap is not fixing it.** The schema endpoints were flagged three
  times across three sessions before anyone turned them off.

### What does not apply here

HIPAA, SOC 2, vendor governance, and audit-evidence process. This project has
no regulated data, no contractual commitments, no vendors processing data, and
no auditor. Mapping it to SOC 2 would spend effort away from the controls that
matter.

That changes if paid registration ships (`docs/ideas.md`) — payment brings a
data regime this project deliberately does not have today.

## Boundaries this project defends

These are enforced and pinned by tests. If a change makes one of these tests
fail, the change is wrong until proven otherwise:

| Boundary | Test |
| --- | --- |
| A pod's room token reaches only its own seat holder | `TestPlayerView` |
| Entrant ids on the wire are opaque; the integer PK never leaves the server | `TestEntrantIdsAreOpaque` |
| Claiming a tournament spot never links an account, even when signed in | `TestIdentityStaysSeparate` |
| An organizer's ruling is never overwritten by an automatic result | `TestResults` |

## Engineering expectations

- **Tests are a gate, not a courtesy.** CI enforces 90% backend coverage and
  the frontend thresholds in `frontend/vite.config.ts`. Regression tests for
  user-reported bugs are expected — several exist precisely because a bug came
  back.
- **A settings flag that promises behaviour must implement it.** This project
  shipped three settings that were read by nothing (`timeCalledPolicy`,
  `collectWizardsEmail`, and a status that could never be reached). Adding a
  config key with no code behind it is worse than omitting the feature.
- **Don't claim something works without checking.** Run the suite. Read the
  output. "Should work" is not a result.
- **Rules citations must be real.** Where this app implements tournament rules,
  cite the actual document and version (see `docs/tournament-api-contract.md`).
  A plausible-sounding rule reference is worse than none.

## The three surfaces

Every feature belongs to exactly one of these. **Decide which before writing
code** — the surface determines who can reach it, what it may assume, and where
it lives.

| Surface | Who | Assumes | Lives in |
| --- | --- | --- | --- |
| **Table** | Anyone at a game, no account | Nothing. Mobile-first. A player may be anonymous, may have joined by QR, may lose their token | `backend/app/table.py`, `frontend/src/table/` |
| **Tournament** | Organizers (account + email) and entrants (token) | An event exists and someone is running it. Desktop-first for the organizer console, mobile for players | `backend/app/tournaments.py`, `frontend/src/tournament/` |
| **Admin** | Operators of this deployment, set by `TABLE_ADMINS` | Full trust. Acts across all events and rooms | `backend/app/admin.py`, `frontend/src/admin/` |

**Choosing:**

- If an ordinary player at a table needs it → **table**.
- If it only makes sense while an event is running → **tournament**.
- If it acts across events, or on someone else's data, or needs to see the
  instance as a whole → **admin**.

**Rules that follow from the split:**

- **Never solve an admin problem in the table surface.** "Let the host force-end
  any room" is an admin feature wearing a player's clothes.
- **The tournament surface may use the table surface, never the reverse.** A pod
  is backed by an ordinary room, and `table.py` must keep working with no
  tournament in sight. It reaches tournaments only through
  `report_tournament_result` and the read-only clock context.
- **Admin is unlisted but not hidden.** Nothing links to `/admin`, and that is
  not a control. Access is `TABLE_ADMINS` plus an account session, checked
  server-side on every endpoint. Non-admins get **404, not 403**, so probing
  reveals nothing.
- **Admin actions are logged; the other two are not.** Every state change made
  through admin writes to `admin_log` with actor, action, target and reason.
  This is the one surface acting on people who cannot see it happening.
- **Admin reads counts, not contents.** It shows how many rooms exist, not
  what's in them, and never a player's notes. Operating the instance does not
  require reading anyone's game.

## Layout

- `backend/app/` — FastAPI. `db.py` owns the schema and migrations; `table.py`
  rooms and games; `tournaments.py` events; `admin.py` the operator surface;
  `accounts.py` optional accounts; `limits.py` rate limiting and bans;
  `games.py` game profiles.
- `frontend/src/` — Vite + React + TS. `table/`, `tournament/`, `admin/`.
- `docs/` — design, the API contract, security decisions, and an ideas parking
  lot that is explicitly not a roadmap.
