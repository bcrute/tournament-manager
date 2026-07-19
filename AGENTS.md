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

## Layout

- `backend/app/` — FastAPI. `db.py` owns the schema and migrations; `table.py`
  rooms and games; `tournaments.py` events; `accounts.py` optional accounts;
  `limits.py` rate limiting and bans; `games.py` game profiles.
- `frontend/src/` — Vite + React + TS. `table/` the game app, `tournament/` the
  event app.
- `docs/` — design, the API contract, security decisions, and an ideas parking
  lot that is explicitly not a roadmap.
