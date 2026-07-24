# Working on this project

## Setting up on a new machine

The repo is self-contained for *understanding* the project. Three things are
not in it and never should be:

1. **A GitHub SSH key to push.** Generate one, register it on the account
   (Settings → SSH and GPG keys), and pin it *per host* so the agent's other
   keys aren't offered first:
   ```
   ssh-keygen -t ed25519 -f ~/.ssh/<machine>_github_ed25519 -C "$(hostname)" -N ""
   git remote set-url origin git@github.com:bcrute/tournament-manager.git
   ```
   ```
   # ~/.ssh/config
   Host github.com
     IdentitiesOnly yes
     IdentityFile ~/.ssh/<machine>_github_ed25519
   ```
   Pin it here, not with `git config core.sshCommand`. That setting applies to
   every remote in the clone regardless of host, so with more than one remote it
   sends the same key everywhere — which still authenticates if the keys sit on
   one account, and quietly defeats having separate keys at all.

   Note that an SSH key only authenticates git. Anything touching the GitHub
   **API** — repository secrets, releases, the `gh` CLI — needs a personal
   access token instead; the key cannot reach those endpoints.

2. **A toolchain.** Nothing here assumes node or python are installed
   system-wide. `npm ci` in `frontend/`, a venv from `backend/requirements*.txt`,
   and `npx playwright install chromium` for the browser tests.

3. **Server environment variables**, which live on the deployment in
   `/opt/apps/mtg/mtg.env` (mode 600, never in the repo; the deploy copies
   `docker-compose.yml` over the VPS dir but not this file, and compose loads it
   via an optional `env_file`): `TABLE_ADMINS` (admin surface is absent without
   it — currently unset, so admin is off), `TABLE_IP_SALT` (set 2026-07-23, so
   bans survive redeploys), `TABLE_DEV_DOCS` (unset → docs off in production).

The reverse proxy is the other piece not shipped by the deploy: Caddy's config
is versioned at [`deploy/Caddyfile`](deploy/Caddyfile) but applied to the VPS by
hand. It is deliberately thin — the app owns every security header (see
`docs/security.md` gap 5), so don't reintroduce header directives there.

**Verifying a deploy:** compare the bundle hash the site serves against your
local `frontend/dist/` build. Checking an API endpoint proves the server
updated, not that any browser sees it — that distinction hid a day of invisible
deploys once already.

**GitHub is the origin, and the only deployer.** `origin` is
`bcrute/tournament-manager` (public); it builds and ships to the VPS from
[`.github/workflows/`](.github/workflows).

The `gitea` remote is the pre-migration home, kept for history and no longer
pushed to. Do not resume pushing to it without thought: `.gitea/workflows/` is
gone, and Gitea falls back to `.github/workflows/` when that directory is
absent, so a push there would hand its self-hosted runner the deploy job and put
two pipelines on the same commit. Disabling Actions on the Gitea repo, or
putting a workflow back in `.gitea/workflows/` to suppress the fallback, are the
two ways to make it safe again.

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
  `collectWizardsEmail`, and a status that could never be reached). All three
  are now genuinely read — but the failure mode inverted rather than went away:
  settings are whitelist-filtered on create, so a key the server does not
  implement is **dropped silently and returns 200**. A design doc promising a
  setting that does not exist is now the likelier defect. See
  `docs/tournament-api-contract.md` §6a, which is the authoritative list.
- **Do not invent a citation.** Standards, control IDs, and tournament rules
  must be ones you have actually read. See `docs/tournament-api-contract.md`
  for how rules citations are handled.
- **Surface the tradeoff instead of quietly taking it.** Say the secure option
  costs something and let a human choose.
- **Reporting a gap is not fixing it.** The schema endpoints were flagged three
  times across three sessions before anyone turned them off — they are off now,
  behind `TABLE_DEV_DOCS`. Three sessions is the number to beat.

### What does not apply here

HIPAA, SOC 2, vendor governance, and audit-evidence process. This project has
no regulated data, no contractual commitments, no vendors processing data, and
no auditor. Mapping it to SOC 2 would spend effort away from the controls that
matter.

**That changes at payment tier 2** (`docs/events-platform.md` §9). Processing
payment data on a shop's behalf makes them the controller and us the processor,
which brings data processing agreements, breach notification duties and
subprocessor disclosure. None of it applies today; all of it applies the day
automated payment tracking ships, and this section must be rewritten in that
same change rather than after it.

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

- **Tests are a gate, not a courtesy.** The gate is `--cov-fail-under=90` in
  the **Dockerfile**, alongside `npm run test` and the thresholds in
  `frontend/vite.config.ts` — not in `.github/workflows/`, which only builds the
  image. Looking only at the workflow would tell you no gate exists. Regression
  tests for user-reported bugs are expected — several exist precisely because a
  bug came back.
- **A settings flag that promises behaviour must implement it.** Adding a
  config key with no code behind it is worse than omitting the feature; see the
  agent rules above for how this one has evolved.
- **Don't claim something works without checking.** Run the suite. Read the
  output. "Should work" is not a result.
- **Rules citations must be real.** Where this app implements tournament rules,
  cite the actual document and version (see `docs/tournament-api-contract.md`).
  A plausible-sounding rule reference is worse than none.

## The table layer is frozen

Lifetap is in active use. An events platform is being designed above all of
this (`docs/events-platform.md`), and it sits **two layers above** the table —
so no part of that work may change `backend/app/table.py`, the room API, or
`frontend/src/table/`. If a design appears to require it, the design is wrong;
say so rather than reaching down.

This is not a general freeze on the table surface — bug fixes to lifetap itself
are fine. It is a rule about which direction new work may reach.

## The three surfaces

Every feature belongs to exactly one of these. **Decide which before writing
code** — the surface determines who can reach it, what it may assume, and where
it lives.

| Surface | Who | Assumes | Lives in |
| --- | --- | --- | --- |
| **Table** | Anyone at a game, no account | Nothing. Mobile-first. A player may be anonymous, may have joined by QR, may lose their token | `backend/app/table.py`, `frontend/src/table/` |
| **Tournament** | Organizers (account + email) and entrants (token) | An event exists and someone is running it. Mobile-first throughout — the console gains a sidebar on wide screens, it is not designed for one | `backend/app/tournaments.py`, `frontend/src/tournament/` |
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

## Front-end structure

Three layouts, in `frontend/src/layouts/`. A page picks one; it never invents
its own chrome. Navigation is data in `frontend/src/nav.ts`, so adding a
section is a line in a list.

| Layout | Used by | Shape |
| --- | --- | --- |
| `SiteLayout` | `/` | The public website. One page today, nav ready for more |
| `PlayLayout` | table lobby, dashboard, tournament player | Mobile-first single column, bottom nav. `bare` for full-viewport pages like the room |
| `ConsoleLayout` | tournament organizer, admin | Sections as a tab strip on a phone, a sidebar past 52rem. A persistent status slot for the round clock |

**Why three and not one:** a player screen is one task, thumb-first. A console
is several sections someone moves between while an event runs, with state that
must stay visible throughout. Forcing the console into the player shell is what
made the organizer view one enormous scrolling page.

**Console sections are routes, not tabs in state**
(`/tournament/:code/organize/pods`, `/admin/:section`). An organizer can
bookmark the standings, reload without losing their place, and the browser Back
button does what it should.

**Icons, never emoji.** Every glyph comes from `Icon.tsx` — a single-colour
outline set that inherits `currentColor`, so it themes and renders identically
everywhere. Emoji can't be recoloured, look different on every platform, and
several carry skin-tone or gender variants we'd be choosing on someone's
behalf. An icon standing alone takes a `label`; beside text it stays
`aria-hidden`.

**Accessibility is part of done, and wrong ARIA is worse than none.** This
project briefly shipped `role="menu"`/`role="menuitem"` without arrow-key
handling — announcing a menu to a screen reader that doesn't behave like one,
and breaking every `getByRole("button")` query at the same time. Prefer native
semantics; add ARIA only when implementing the whole pattern. Icon-only
controls need an accessible name, focus must never be stranded (Escape closes
and returns it), and `frontend/e2e/a11y.spec.ts` pins the skip link, focus
return, accessible names, `lang`, and landmarks.

**Mobile-first is not negotiable, including the console.** Base rules are the
phone; media queries add room and never take it away. An organizer is usually
holding a phone and walking between tables.

## Layout

- `backend/app/` — FastAPI. `db.py` owns the schema and migrations; `table.py`
  rooms and games; `tournaments.py` events; `admin.py` the operator surface;
  `accounts.py` optional accounts; `limits.py` rate limiting and bans;
  `games.py` game profiles; `pairing.py` the pod pairer; `audit.py` the audit
  and security logs.
  - **`pairing.py` is pure.** No database, no clock, no unseeded randomness —
    deterministic given `(entrants, history, seed)`, which is what makes a
    re-roll reproducible and a disputed pairing re-derivable. Keep it that way;
    anything needing I/O belongs in `tournaments.py`.
  - **`audit.py` is where two of the rules above are actually implemented** —
    "admin actions are logged" and "log the decision, not the secret".
- `frontend/src/` — Vite + React + TS. `site/` the public page, `table/`,
  `tournament/`, `admin/`, with `layouts/` and `nav.ts` shared between them.
  End-to-end specs are in `frontend/e2e/`, run by `npm run e2e` and excluded
  from vitest.
- `docs/` — `tournament-api-contract.md` is what the server actually serves and
  wins any disagreement; `tournament-api-design.md` is the intent and stress
  test behind it; `security.md` the threat model; `tournament-research.md` the
  research and the decisions taken; `commercial-position.md` the paid-tier
  question; `events-platform.md` the design for the events layer above all of
  this, none of which is built; `ideas.md` a parking lot that is explicitly not
  a roadmap.
