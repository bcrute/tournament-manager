# Working on this project

## Setting up on a new machine

The repo is self-contained for *understanding* the project. Four things are
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

4. **VPS SSH access — only for manual host operations.** Routine deploys never
   need it: the workflow has its own key in the repo's Actions secrets
   (`VPS_SSH_KEY`, base64-encoded; its public half is the
   `github-actions-deploy-mtg` entry in root's `authorized_keys` — minted
   2026-07-26 after the migrated secret turned out to have never been
   authorized on the VPS, which silently failed every GitHub deploy at the
   first SSH step while the site kept serving the last home-runner build). What does need it: editing the root
   Caddyfile, `mtg.env`, or anything in `deploy/README.md`'s runbook. Access is
   `root@74.208.222.65`, host key pinned in `deploy.yml`. Keys are per-machine
   and named for what they are (e.g. `~/.ssh/social_vps_ed25519`); to work from
   a new machine, generate one and append its `.pub` to the VPS's
   `/root/.ssh/authorized_keys` from a machine that already has access — don't
   copy private keys between machines. The VPS is shared with
   social.skadoosh.dev: stay inside this app's namespace (`/opt/apps/mtg`,
   `/opt/caddy/sites/mtg.caddy`) unless the task is explicitly cross-app.

The reverse proxy is shared ground: one Caddy on the VPS fronts every app on
the host — social.skadoosh.dev is an independent app living behind the same
proxy. Each app owns one `sites/*.caddy` vhost file; this repo's is
[`deploy/caddy/sites/mtg.caddy`](deploy/caddy/sites/mtg.caddy), shipped by the
deploy (validated against the merged config, then a graceful reload — see
[`deploy/README.md`](deploy/README.md)). The root Caddyfile stays manual, and
nothing in this repo may write any other app's vhost. The vhost is deliberately
thin — the app owns every security header (see `docs/security.md` gap 5), so
don't reintroduce header directives there.

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
| A room is opened by its 128-bit `url_id`; the five-character `code` opens nothing | `TestTheCodeOpensNothing`, `TestIdentifierQuality` |
| A pod's room identifier reaches only its own seat holder | `TestPlayerView` (poll), `TestTournamentSocket` (push), `TestTournamentPodHandoff` |
| Entrant ids on the wire are opaque; the integer PK never leaves the server | `TestEntrantIdsAreOpaque` |
| Claiming a tournament spot never links an account, even when signed in | `TestIdentityStaysSeparate` |
| An organizer's ruling is never overwritten by an automatic result | `TestResults` |
| The anonymous room lookups have a budget of their own, and one flooder cannot deny a room to the people at it | `TestTheBudget`, `TestStrikesInPractice` |
| `X-Forwarded-For` is trusted only because the deployment makes it unspoofable | `TestTheTrustBoundary` |
| `hasEmail` means *confirmed*; an unverified address never satisfies anything | `TestHosting`, `TestTheMigration` |
| The forgotten-password endpoint reveals nothing about which accounts exist | `TestForgotIsBlind` |
| A confirmation token cannot reset a password, and vice versa | `TestConfirming`, `TestResetting` |
| No endpoint ever returns a recovery address | `TestRecoveryEmailIsWriteOnly` |

### Two credentials that are not what they look like

Two things in this codebase read like identifiers and behave like passwords.
Both were treated as the former for a long time, and both were corrected in the
same week; the shape of the mistake is worth recognising because it will happen
again somewhere else.

A **room's `url_id`** and an **emailed link token** are credentials. Neither may
appear in a URL path or query string, because both would then be in an access
log, a `Referer`, and a browser history. Both travel in POST bodies or link
fragments, and both are 128 bits or more. When adding anything that hands out
access without a session, ask which of those two shapes it is — and if it is a
short human-readable string, it is not a credential and must not be made into
one.

### The two room identifiers

`rooms.code` is five characters from a 31-letter alphabet — read aloud across a
table, and therefore walkable in about a day. `rooms.url_id` is
`secrets.token_urlsafe(16)`, 128 bits, base64url, **case-sensitive**.

Only `url_id` opens a room. Every unauthenticated route — `POST /rooms/join`,
`POST /rooms/seats`, `POST /rooms/reclaim` — takes it as `roomId` in the request
**body**, never in the path, so it stays out of access logs and `Referer`
headers. Invitation links put it in a **fragment** (`/table#r/<id>`), which
browsers never send to a server. Routes that already have a player token keep
keying on `code`: it is not a secret, it just is not a credential on its own,
and sessions held before this change had to keep working.

`ANONYMOUS_DOORS` in `backend/tests/test_room_boundary.py` is the explicit list
of routes that take a room identifier without a credential. A new one belongs
in that list.

### Sending email

`backend/app/mail.py` is the only module that talks to an SMTP server, and a
test asserts that. `mail_providers.py` beside it is a registry of settings, not
a stack of API clients — every provider worth using speaks SMTP, and what
actually differs between them is host, port, TLS flavour and what they expect
in the username field. `scripts/mailcheck` prints that per provider and will
send a test message; use it rather than guessing, because the classic failure
(Resend wants the literal string `resend` in the username) fails as though the
password were wrong. Nothing is configured by default: `build_mailer` returns
`OffMailer`, which raises, and the routes turn that into a 503. That is
deliberate — a silently swallowed send produces a recovery flow that tells the
user to check an inbox nothing will arrive in. `docker-compose.yml` lists the
variables and what leaving them unset costs.

Tests use `FakeMailer` (recording, installed in `conftest.py`); the browser
suite uses `FileMailer` through `TABLE_MAIL_FILE`, so it reads a real
confirmation link out of a real message rather than skipping confirmation.

## Engineering expectations

- **Tests are a gate, not a courtesy.** The gate is `--cov-fail-under=90` in
  the **Dockerfile**, alongside `npm run test` and the thresholds in
  `frontend/vite.config.ts` — not in `.github/workflows/`, which only builds the
  image. Looking only at the workflow would tell you no gate exists. Regression
  tests for user-reported bugs are expected — several exist precisely because a
  bug came back.
- **Run the gate here, not on GitHub's dime — a deploy no longer runs one.**
  Since 2026-08-02 `deploy.yml` builds `--target runtime`, which runs **no
  tests at all**. The image build was 2m26s of a 2m43s deploy, nearly all of it
  re-running a suite that had already passed locally. Measured cold, from
  scratch: the runtime target is 27s and the test target 155s — the suites are
  the entire difference. A push straight to `main`
  is now gated by `scripts/ci` and by nothing else. That is a process gate, not
  a mechanism: the shipped image used to carry a `/tests-passed` marker making
  an untested build impossible, and it does not any more.

  | | runs | when |
  | --- | --- | --- |
  | `deploy.yml` | `--target runtime`, ship | push to `main` |
  | `ci.yml` | `--target test` | pull requests |
  | `full.yml` | `--target test` **and Playwright** | `workflow_dispatch` only |
  | `security.yml` | semgrep, pip-audit, npm audit | weekly, or a lockfile change |

  Locally, `scripts/ci` builds both targets — the same signal as a PR, for no
  minutes. `--fast` skips Docker for iteration and is not a substitute: it uses
  whatever Python and packages this machine has, which is the class of
  difference that makes a build pass here and fail there. `--e2e` rebuilds the
  bundle and runs Playwright; `--all` does everything.

- **Nothing runs Playwright automatically, on any event.** Not on push, not on
  a PR. It needs a browser download and a live server, so it lives in
  `full.yml` behind `workflow_dispatch` — `gh workflow run "full suite"`, with
  a `project` input to run just `mobile` or just `desktop`. A green badge says
  nothing about the browser suite; `scripts/ci --e2e` before anything that
  touches the table, the account area, or a layout.

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
| A room is opened by its 128-bit `url_id`; the five-character `code` opens nothing | `TestTheCodeOpensNothing`, `TestIdentifierQuality` |
| A pod's room identifier reaches only its own seat holder | `TestPlayerView` (poll), `TestTournamentSocket` (push), `TestTournamentPodHandoff` |
| Entrant ids on the wire are opaque; the integer PK never leaves the server | `TestEntrantIdsAreOpaque` |
| Claiming a tournament spot never links an account, even when signed in | `TestIdentityStaysSeparate` |
| An organizer's ruling is never overwritten by an automatic result | `TestResults` |
| The anonymous room lookups have a budget of their own, and one flooder cannot deny a room to the people at it | `TestTheBudget`, `TestStrikesInPractice` |
| `X-Forwarded-For` is trusted only because the deployment makes it unspoofable | `TestTheTrustBoundary` |
| `hasEmail` means *confirmed*; an unverified address never satisfies anything | `TestHosting`, `TestTheMigration` |
| The forgotten-password endpoint reveals nothing about which accounts exist | `TestForgotIsBlind` |
| A confirmation token cannot reset a password, and vice versa | `TestConfirming`, `TestResetting` |
| No endpoint ever returns a recovery address | `TestRecoveryEmailIsWriteOnly` |

### Two credentials that are not what they look like

Two things in this codebase read like identifiers and behave like passwords.
Both were treated as the former for a long time, and both were corrected in the
same week; the shape of the mistake is worth recognising because it will happen
again somewhere else.

A **room's `url_id`** and an **emailed link token** are credentials. Neither may
appear in a URL path or query string, because both would then be in an access
log, a `Referer`, and a browser history. Both travel in POST bodies or link
fragments, and both are 128 bits or more. When adding anything that hands out
access without a session, ask which of those two shapes it is — and if it is a
short human-readable string, it is not a credential and must not be made into
one.

### The two room identifiers

`rooms.code` is five characters from a 31-letter alphabet — read aloud across a
table, and therefore walkable in about a day. `rooms.url_id` is
`secrets.token_urlsafe(16)`, 128 bits, base64url, **case-sensitive**.

Only `url_id` opens a room. Every unauthenticated route — `POST /rooms/join`,
`POST /rooms/seats`, `POST /rooms/reclaim` — takes it as `roomId` in the request
**body**, never in the path, so it stays out of access logs and `Referer`
headers. Invitation links put it in a **fragment** (`/table#r/<id>`), which
browsers never send to a server. Routes that already have a player token keep
keying on `code`: it is not a secret, it just is not a credential on its own,
and sessions held before this change had to keep working.

`ANONYMOUS_DOORS` in `backend/tests/test_room_boundary.py` is the explicit list
of routes that take a room identifier without a credential. A new one belongs
in that list.

### Sending email

`backend/app/mail.py` is the only module that talks to an SMTP server, and a
test asserts that. `mail_providers.py` beside it is a registry of settings, not
a stack of API clients — every provider worth using speaks SMTP, and what
actually differs between them is host, port, TLS flavour and what they expect
in the username field. `scripts/mailcheck` prints that per provider and will
send a test message; use it rather than guessing, because the classic failure
(Resend wants the literal string `resend` in the username) fails as though the
password were wrong. Nothing is configured by default: `build_mailer` returns
`OffMailer`, which raises, and the routes turn that into a 503. That is
deliberate — a silently swallowed send produces a recovery flow that tells the
user to check an inbox nothing will arrive in. `docker-compose.yml` lists the
variables and what leaving them unset costs.

Tests use `FakeMailer` (recording, installed in `conftest.py`); the browser
suite uses `FileMailer` through `TABLE_MAIL_FILE`, so it reads a real
confirmation link out of a real message rather than skipping confirmation.

## Engineering expectations

- **Tests are a gate, not a courtesy.** The gate is `--cov-fail-under=90` in
  the **Dockerfile**, alongside `npm run test` and the thresholds in
  `frontend/vite.config.ts` — not in `.github/workflows/`, which only builds the
  image. Looking only at the workflow would tell you no gate exists. Regression
  tests for user-reported bugs are expected — several exist precisely because a
  bug came back.
- **Run the gate here, not on GitHub's dime.** `scripts/ci` runs `docker build`,
  which is the entire thing any workflow does — same signal, no minutes. Use it
  before opening a PR or pushing to `main`; those are the only two events that
  spend anything, and a failure discovered on the runner costs a full build to
  learn what a local one would have told you.

  `scripts/ci --fast` skips Docker and runs the same three checks directly for
  iteration. It is not a substitute: it uses whatever Python and packages are
  installed on this machine, which is the class of difference that makes a build
  pass locally and fail in CI.

  `scripts/ci --e2e` rebuilds the bundle and runs Playwright — **which no
  workflow runs at all.** There is no browser job anywhere in
  `.github/workflows/`, so the e2e suite has only ever run on a developer's
  machine. A green CI badge says nothing about it. It rebuilds first because
  testing a stale `dist/` has fooled this project more than once.
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

**Accounts are not a fourth surface.** They are shared ground, like
`layouts/` and `nav.ts`: `backend/app/accounts.py` and
`frontend/src/account/` hold sign-in, the account area (`/account`, with
overview, games, notes and settings sections) and the `useAccount` hook, and
all three surfaces use them. The rule that follows is about *direction*, and it
is the same one the surfaces have: **`account/` may not import from `table/`,
`tournament/` or `admin/`.** It sits underneath all three. Sign-in used to live
in `table/`, which meant the tournament and admin consoles both reached
sideways into the table surface to find it — the import that made the split
obvious.

An account is still optional for playing, and that is not negotiable: the
account area is somewhere to *go*, never somewhere you are *sent*. Nothing in
the table surface may require one.

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
section is a line in a list. The layout owns the `<main>` landmark — pages
render plain containers inside it.

Site navigation is one component, `SiteNav`: a hamburger menu on a phone,
inline links past 60rem. All three layouts render it. The room is the one
exception — a card fills that screen, and `RoomBar` is its chrome, with the
same hamburger grammar (leading trigger, `aria-expanded`, Escape closes and
hands focus back).

| Layout | Used by | Shape |
| --- | --- | --- |
| `SiteLayout` | `/`, `/privacy` | The public website: `SiteNav` plus a footer |
| `PlayLayout` | table lobby, the account area, tournament host & player | `SiteNav` over a mobile-first single column |
| `ConsoleLayout` | tournament organizer, admin | `SiteNav`, then the event bar (title, status slot for the round clock), then sections — a tab strip on a phone, a sidebar past 52rem |

**Navigation is one bar, `layouts/SiteNav.tsx`, and every layout renders it.**
Links sit across the top past 60rem and collapse behind a hamburger below it —
the room bar's breakpoint, so the two are never in different modes on one
screen. Before this the app had three answers: the site had a top bar, the play
shell duplicated that markup *and* carried a bottom tab strip, and the console
had no app navigation at all, so running an event was a dead end. Adding a
destination is a line in `SITE_NAV` and it appears everywhere at once.

The console's section tabs are a **different axis** — they move within one
event, not around the app — so they stay visible rather than folding into the
same menu. The room (`bare`) keeps its own bar for the same reason it always
did: it owns the whole viewport.

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
  - **`db.py`'s `q()` returns rows, not a cursor, and that is load-bearing.**
    One SQLite connection is shared by every request. `q()` used to hand back
    the live cursor with `_db_lock` already released, so callers fetched
    outside it — and another thread's `commit()` landing between `execute()`
    and `fetchone()` reset the pending statement, making `fetchone()` return
    `None` for a row that was certainly there. No exception, just a wrong
    answer, inside `get_player()`, which turned it into **403 "not a player in
    this room"** for a seated player at random under load. Everything is
    fetched inside the lock now and returned as a `Result`. If you add a query
    helper here, fetch inside the lock; a bare cursor escaping it is the bug.
    Pinned by `tests/test_db_concurrency.py`.
  - **`pairing.py` is pure.** No database, no clock, no unseeded randomness —
    deterministic given `(entrants, history, seed)`, which is what makes a
    re-roll reproducible and a disputed pairing re-derivable. Keep it that way;
    anything needing I/O belongs in `tournaments.py`.
  - **`audit.py` is where two of the rules above are actually implemented** —
    "admin actions are logged" and "log the decision, not the secret".
- `frontend/src/` — Vite + React + TS. `site/` the public page, `table/`,
  `tournament/`, `admin/`, with `account/`, `layouts/` and `nav.ts` shared
  between them. Each area owns its own stylesheet and its own class prefix
  (`account.css` is entirely `acct-`); `table.css` is the flat one that taught
  us why, having shipped three regressions from two components accidentally
  sharing a class name.
  End-to-end specs are in `frontend/e2e/`, run by `npm run e2e` and excluded
  from vitest.
- `docs/` — `tournament-api-contract.md` is what the server actually serves and
  wins any disagreement; `tournament-api-design.md` is the intent and stress
  test behind it; `security.md` the threat model; `tournament-research.md` the
  research and the decisions taken; `commercial-position.md` the paid-tier
  question; `events-platform.md` the design for the events layer above all of
  this, none of which is built; `ideas.md` a parking lot that is explicitly not
  a roadmap.
