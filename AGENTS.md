# Working on this project

## Security baseline

This project follows the security reference at
`ssh://git@192.168.30.4:2222/ben/security-docs.git`. Clone it alongside this
repo and read its `AGENTS.md` before designing anything that touches
authentication, authorization, or personal data.

The short version, which applies to every change here:

- **OWASP Top 10 always applies.** The compliance material in that repo is
  conditional and mostly does not apply to this project — see below.
- **Deny by default.** An endpoint with no authorization check is a bug.
- **Never trust the client.** UI restrictions are not access control.
- **Collect the minimum.** This project's central design decision is that
  playing requires no account and no personal data. Do not erode it.

This project's answers to the reference's pre-ship checklist are in
[`docs/security.md`](docs/security.md). Read it before adding a feature that
collects data, adds a credential, or crosses a trust boundary — several
questions are already answered, and a few gaps are deliberately accepted with
reasons.

### What applies here, and what doesn't

Applies: OWASP Top 10, the threat-model method, the standards reference.

Does **not** apply: HIPAA and SOC 2 readiness, vendor governance, audit
evidence and control ownership. This project has no regulated data, no
customers with contractual commitments, no vendors processing data, and no
auditor. Mapping it to SOC 2 would be effort spent away from the controls that
actually matter here.

That judgement changes if paid registration ships (`docs/ideas.md`) — payment
brings a data regime this project deliberately does not have today.

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
