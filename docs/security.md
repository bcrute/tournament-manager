# Security decisions

This project's threat model, security decisions, and known gaps. It is
self-contained — nothing here requires another repository to be checked out.

The questions it answers come from a general security baseline kept separately
(`ssh://git@192.168.30.4:2222/ben/security-docs.git`), which is the source of
record for *how to think about* this. The answers are here, because they are
about this project.

Rules from the reference that apply here: a decision without a rationale is
only an assertion; "deferred" needs an owner and a trigger; sections that don't
apply are marked not-applicable explicitly rather than deleted.

Owner for everything below: Ben. Last reviewed 2026-07-19 (post-audit);
re-checked against the code 2026-07-20, which closed the schema-endpoint and
application-logging gaps and narrowed T10.

---

## What this project is, in security terms

An anonymous-first app for tabletop game nights and tournaments. The defining
decision — which most of the rest follows from — is that **playing requires no
account and no personal data**. A player supplies a display name they choose,
and nothing else. **Playing** never requires an account — accounts exist only
for history and notes. **Hosting** a tournament does require one, plus a
recovery email, because an organizer losing access mid-event strands every
table. Stating it as "accounts are optional" without that distinction is
inaccurate and sets up an organizer for a surprise.

The practical consequence is that **most data-protection questions are answered
by not having the data**. That is a deliberate control, not an accident of
scope, and it should survive future features (see `docs/ideas.md`, "Identity").

---

## Threat model

Derived from the method in the security baseline, applied to this app. The rule
that makes it useful: **a threat is only mitigated if this table names the
mechanism that mitigates it.** A generic control name with no implementation is
an open threat.

### Actors and what they start with

| Actor | Starts with | Wants |
| --- | --- | --- |
| Passer-by | Nothing but the public URL | Any access at all |
| Code holder | A tournament or room code, shared openly at the venue | To act as someone at a table they aren't at |
| Player | A room token, or an entrant token for one event | To alter a result, take another seat, or read another table |
| Organizer | An account session owning one tournament | To act on events they don't own |
| Account holder | Optional account, history, notes | Another account's history |

### Trust boundaries

1. **Anonymous → room** — crossed by holding a room code or room token.
2. **Anonymous → tournament** — crossed by holding a tournament code.
3. **Player → their own pod** — a token grants one seat, not the table.
4. **Organizer → their own tournament** — a session owns one event, not all.
5. **Anonymous → account** — password plus optional recovery.
6. **Account → admin** — an account session whose username is in `TABLE_ADMINS`.

### Threats and the actual control

| # | Boundary | Threat | Mechanism in this codebase | State |
| --- | --- | --- | --- | --- |
| T1 | 2→3 | Force a match result by counting a pod's turns | `advance_turn` requires an entrant token seated in that pod, or the organizer session; pod resolved via `pod_in()` | Mitigated — `TestPodAuthorization` |
| T2 | 4 | Organizer of A writes results or extends clocks in B | `report_result`, `timer extend`, `call_official` all resolve through `pod_in()`, scoped by tournament | Mitigated — `TestPodAuthorization` |
| T3 | 1 | Seize an occupied seat using a published room code | Room codes are no longer published; only the organizer and that table's own players receive one | Mitigated — `TestRoomCodesAreNotPublished` |
| T4 | 3 | Read another player's seat credential | Room token personalised onto the caller's own seat only, never in the shared pod list | Mitigated — `TestPlayerView` |
| T5 | 2 | Claim every seat in an event before real players arrive | `/claim` rate-limited as *sensitive* (20 per 10 min); claims are first-come and the organizer can release | Partially mitigated — a determined attacker with the code can still race real players |
| T6 | 2 | Enumerate platform size from a public roster | Entrant ids on the wire are random and tournament-scoped; the integer PK never leaves the server | Mitigated — `TestEntrantIdsAreOpaque` |
| T7 | 5 | Enumerate usernames | Identical response text, and a throwaway scrypt verification when no account matches so timing matches too | Mitigated — `TestAuthTimingAndSessions` |
| T8 | 5 | Reuse a stolen session cookie | httpOnly + Secure + SameSite; 90-day absolute expiry with a 30-day idle expiry that now actually updates | Mitigated |
| T9 | 5 | Brute-force a password or recovery code | scrypt n=2^16; sensitive endpoints 20 per 10 min; escalating IP bans 1h→6h→24h→7d | Mitigated |
| T10 | any | Probe the app without leaving a trace | `security_log` via `audit.py`: auth failures, unknown-user attempts, admin denials, rate-limit trips and bans, all keyed to a salted client id. 30-day retention, pruned on the hourly sweep | Partially mitigated — the tournament layer records nothing; see gaps |
| T11 | 2 | Entrant token captured from a URL | Token travels as `?token=`; the reverse proxy must strip query strings from access logs | **Partially mitigated** — depends on proxy config not in this repo |
| T12 | 1 | Denial of service by room or event creation | Per-client rate limits; rooms idle out at 3h, tournaments at 12h | Mitigated |
| T18 | 1 | Enumerate room URLs to find live games | The address bar carries `rooms.url_id` — 128 random bits — not the five-character code. Pinned by `TestRoomUrlId` and a browser test | Mitigated |
| T19 | 1 | Guess room codes at the join endpoint | A code is short by necessity (it is read aloud at a table), so the defence is behavioural: a join naming a room that doesn't exist is a strike, escalating into the existing ban ladder | Mitigated — `TestJoinEnumeration` |
| T13 | 3 | Alter another player's life total | Every room mutation resolves the actor from `X-Player-Token` scoped to that room | Mitigated |
| T14 | 4 | Player disputes an organizer's ruling | Results are versioned and never mutated; `source` records `auto` vs `organizer` | Mitigated by design |
| T15 | 6 | Find and use the unlisted admin surface | Not the URL — `require_admin` on every endpoint, admin list in the environment rather than the database, 404 for everyone else so probing yields nothing | Mitigated — `test_admin.py::TestAccess` |
| T16 | 6 | Escalate to admin by writing to the database | Admin membership is read from `TABLE_ADMINS` at call time; no column grants it | Mitigated — `test_admin_is_not_settable_from_the_database` |
| T17 | 6 | An admin quietly alters or ends someone's game | Cannot be prevented — admin is trusted by definition — but every change writes actor, action, target and reason to `admin_log`, and failed actions do not | Detected, not prevented |

### Assumptions

These are part of the model, not omissions from it:

- TLS terminates at Caddy and the app is not directly reachable. Verified by
  `docker-compose.yml` publishing no ports.
- Whoever holds a tournament or room code is entitled to be at that venue.
  Codes are shouted across a game store; they are a convenience, not a secret.
- The host is trusted. A database file readable on the host reveals everything
  the app knows, which is deliberately very little.

---

## Authentication

| Question | Decision | Rationale |
| --- | --- | --- |
| Session timeout | Account sessions expire server-side; the cookie is httpOnly, Secure, SameSite. | Sessions are a convenience over an optional account, not access to sensitive data. |
| Second-factor recovery | No second factor. Recovery is 8 single-use codes, shown once at signup. An email may be stored but **email recovery is not implemented**, so the codes are the only working path and the UI says exactly that. | Requiring MFA on an optional account for a game-night app would cost more accounts than it protects. Recovery codes work without collecting an address. |
| Identity provider dependency | None — no external IdP. | No third-party dependency to be unavailable. |
| Break-glass access | The admin surface *is* the break-glass path. It is off unless `TABLE_ADMINS` names an account, and every action it takes is logged. | A deployment that never sets the variable has no admin surface at all, which is the default. |
| Strong authenticators | Not supported. | See second-factor recovery. |
| Bootstrap/first admin | Admins are named in `TABLE_ADMINS` (an environment variable), matched case-insensitively against an ordinary account. There is no in-app promotion. | Privilege from the environment, not the database: a flag in `accounts` is one bad `UPDATE` or one signup bug away from escalation. Changing it requires restarting the process, which needs host access already. |

**A room has two identifiers, deliberately.** The five-character code is a
credential people read across a table, so it must stay short and therefore
guessable. The URL id is 128 random bits and identifies the room in links,
history and screenshots without being joinable. Conflating them forced one
value to be both typeable and unguessable, which is not possible. The URL id is
explicitly *not* accepted as a join credential — a test pins that, because
making it work "for convenience" would undo the whole point.

**Player and entrant credentials** are bearer tokens, not accounts:

- room token (`X-Player-Token`) — one seat in one room
- entrant token (`?token=`) — one seat in one tournament

Both are `secrets.token_urlsafe(24)`. They are capability tokens: possession is
the authorization, and they grant nothing outside their room or tournament.

---

## Authorization

| Question | Decision | Rationale |
| --- | --- | --- |
| Role model | Four: admin (named in `TABLE_ADMINS`), organizer (owns a tournament), player (holds a token), anonymous. Permissions are additive from nothing. | No role can be over-privileged by default because there is no default grant. |
| Custom roles | Not supported. | No demand, and a role editor is a large attack surface for a game app. |
| Sensitive export | No bulk export exists. | Nothing to export — see data minimisation. |
| Access review cadence | Review `TABLE_ADMINS` whenever it changes, and read `admin_log` after any incident. | The list is short and lives in deployment config, so drift is visible in the diff. |
| Separation of duties | An organizer both runs and rules on their own event, and an admin can act on any event unreviewed. Both accepted. | Inherent to a one-person tournament; the alternative is requiring two staff, which the target user doesn't have. Results are versioned so an override leaves a trail. |

**Enforcement boundaries** — the ones a change could plausibly break:

- `require_organizer` matches the session account against the tournament owner.
- A pod's room token is returned **only** on the caller's own seat, never in the
  pod list every entrant can read. Pinned by tests in `TestPlayerView`.
- Entrant ids on the wire are random and tournament-scoped; the integer primary
  key never leaves the server. Pinned by `TestEntrantIdsAreOpaque`.
- Claiming a spot never links an account, even when the caller is signed in.
  Pinned by `TestIdentityStaysSeparate`.

---

## Credentials and secrets

| Question | Decision | Rationale |
| --- | --- | --- |
| Rotation policy | No expiry on player/entrant tokens; they die with the room or event. | Rooms idle out in 3h, tournaments in 12h. A token outliving its room grants nothing. |
| Rotation mechanics | Not applicable. | |
| Integration credentials | None — the app has no third-party integrations and ships no third-party card data. | |
| Secret storage | Deploy secrets live in the CI secret store and on the host, never in the repo. Passwords are scrypt (n=2^16, r=8, p=1). Recovery codes are stored hashed. | A leaked SSH key earlier in this project's life is why CI secrets are base64-encoded — multiline secrets weren't masked in logs. |

---

## Data protection

| Question | Decision | Rationale |
| --- | --- | --- |
| Backup frequency/retention | **Deferred.** SQLite file on the VPS, no scheduled off-host backup. Owner: Ben. Trigger: before the first real tournament runs on it. | Honest gap. Losing the DB today loses game history and accounts — annoying, not catastrophic, but a live event mid-round would be. |
| Backup encryption | Deferred with the above. | |
| RTO/RPO | Not committed. No SLA is offered to anyone. | Stating a number we don't measure would be worse than stating none. |
| Backup access isolation | Deferred with the above. | |
| Backup immutability | Deferred with the above. | |
| Network segmentation | The database is a local file, not a network service — no listening port to expose. Caddy terminates TLS and is the only public surface. | |

---

## Audit and logging

Three logs, deliberately separate because they have three different readers,
retentions and threat models. All three live in `audit.py` except `events`,
which belongs to the room:

| Log | Reader | Retention | Written by |
| --- | --- | --- | --- |
| `events` | the player, in-game | dies with the room | `table.py` |
| `admin_log` | the operator, after the fact | 365 days | `audit.admin_action()`, only after a privileged action succeeds |
| `security_log` | whoever is investigating | 30 days | `audit.security_event()`, on attack signal |

Event kinds are constants (`AUTH_FAIL`, `AUTHZ_DENY`, `ADMIN_DENY`,
`RATELIMIT_TRIP`, `BAN_ISSUED`, …) rather than free strings, so a typo cannot
quietly create a category nobody queries.

**There is still no `logging` module anywhere in `backend/app/`.** That is the
design, not an omission: everything above is durable and queryable, and stdout
on a single container is neither.

| Question | Decision | Rationale |
| --- | --- | --- |
| Admin actions | Every state change through `/api/admin` records actor, action, target and a free-text reason. Failed actions record nothing. | An audit log that fills with rejected attempts stops being read. |
| Audit immutability | Game events are append-only in practice but not enforced at the database level. Accepted. | The audit consumer is a player wondering who killed them, not a regulator. Hash chaining would be theatre here. |
| Audit granularity | Game events record actor, action, target and timestamp. Result changes are versioned with source (`auto` vs `organizer`) and a note. | An organizer overriding a result is the one action with real consequences, so it keeps history rather than mutating. |
| Audit retention | Tied to the room's lifetime; account history persists until the account is deleted. | |
| Denial logging | Admin denials (`ADMIN_DENY`) and authentication failures are recorded. **Gap: the tournament layer records nothing** — `tournaments.py` does not import `audit` at all, so a 403 from the pod-authorization checks leaves no trace. | The layer that produced five authorization defects is the one that would not show a sixth being probed. |

**Never logged:** tokens, passwords, recovery codes, or raw IP addresses.
Rate limiting identifies clients by a salted HMAC of the IP (`limits.client_id`).
That is pseudonymisation, not anonymisation — IPv4 is brute-forceable given the
salt — and it is documented as such rather than claimed as anonymous.

---

## Data retention and privacy

| Question | Decision | Rationale |
| --- | --- | --- |
| Retention per class | Rooms idle out after 3h (tournament-backed rooms are exempt while the event runs); tournaments after 12h. Ban records retain 30 days. Account history persists until deletion. | |
| Automatic vs manual deletion | Automatic for ephemeral rooms; never automatic for account data. | The reference warns against silent purging. Rooms are transient by design and their loss is expected; a user's history is not. |
| Right to erasure | `/api/account/delete` requires typing the username to confirm. It unlinks the account from games rather than deleting them. | Deleting shared game records would punch holes in other players' history and, for tournaments, in an organizer's standings. Unlinking removes the person, keeps the event intact. |
| Sensitive artifacts | None stored. No recordings, transcripts, uploads, or location data. | |
| Attachment handling | Not applicable — no uploads. | |

**No consent banner, because there is nothing to consent to.** Every stored
item is required to deliver what the user asked for: the room seat, the
tournament seat, the display name they typed, their language, and — only if
they choose to make an account — a sign-in cookie. There is no analytics, no
advertising, and **no third-party requests at all**: no CDN, no hosted fonts,
no embedded widgets. `/privacy` lists every item with its purpose and lifetime,
and `e2e/privacy.spec.ts` asserts the two claims that make the position
defensible — zero foreign requests during a full session, and zero cookies for
a signed-out player.

This is an engineering position, not legal advice. It rests on the storage
being strictly necessary; if anything non-essential is ever added — a
preference nobody asked for, a metric, a hosted font — the position changes and
the banner question returns.

**Personal data actually collected:** a display name (user-chosen, may be a
random default), an optional password, an optional recovery email. No IP-to-user
association, no location, no device identifiers, no third-party analytics.

---

## Session and tenant isolation

Not applicable in the multi-tenant sense — there are no tenants. The equivalent
boundary is the room and the tournament, and both are enforced per request:
every token lookup is scoped by room code or tournament code, so a token from
one never resolves in another. Pinned for tournaments by
`test_a_public_id_from_another_tournament_does_not_resolve`.

Concurrent sessions are unlimited. Accepted: a player legitimately has the same
game open on a phone and a table display.

---

## Integrations and external providers

Not applicable today. The app has no inbound webhooks, no outbound API calls,
and ships no third-party data — Scryfall integration was removed deliberately so
the app carries no third-party card data at all.

Planned integrations (`docs/ideas.md`) must answer this section before shipping:

- **Payment processor** — the design already fixes the two answers that matter:
  the organizer is the merchant of record so the app never holds funds, and card
  data never touches our server (hosted checkout only).
- **Tournament import** — provider data is reference input, never internal
  truth; our own authorization applies independently.

---

## Outbound email

Not applicable — the app sends no email. An optional recovery address is stored
but nothing is currently sent to it, which means **account recovery by email is
not yet implemented**. Recovery codes are the working path. Recorded here
because storing an address that implies a capability the app lacks is exactly
the kind of half-built promise worth naming.

---

## Audit, 2026-07-19

An independent OWASP Top 10 review found **five authorization defects in the
tournament layer, all the same root cause**: a pod id is a global integer and
was being treated as self-authorizing. Fixed, each pinned by a regression test
in `TestPodAuthorization` and `TestRoomCodesAreNotPublished`.

| Was | Impact |
| --- | --- |
| `advance_turn` accepted a token and never checked it | Anyone with a tournament code could count a pod's turns to zero and **force a recorded match result** |
| Every pod's `roomCode` was published to unauthenticated callers | Chained with room reclaim, a stranger could seize an occupied seat, alter life totals, and drive the auto-reported result |
| `report_result` looked pods up by global id after authorizing the tournament | An organizer of one event could write results into another's |
| `timer extend` updated `pods` by client-supplied id, unscoped | Cross-event clock manipulation |
| `call_official` required no token and no pod scoping | A stranger could raise calls on any table, earning it an automatic extension |

Also fixed: `/claim` and `/entrants` were rate-limited as *normal* (900/min)
despite the roster being public, so a script could claim every seat in an event
in seconds; login skipped the scrypt hash entirely when no account matched,
enumerating usernames by stopwatch; and sessions never updated `last_seen`, so
a stolen cookie lived the full 90 days regardless of use (now 30-day idle
expiry).

**One documented decision was reversed.** Official calls previously allowed an
anonymous caller, deliberately, so a player whose phone lost its token could
still raise a hand. That let a stranger with the tournament code aim calls at
any table and earn it free time. Calls now require a token from someone seated
at that table — at a physical event the fallback is raising an actual hand.

The lesson worth keeping: **the room and account layers audited clean, and the
tournament layer did not.** The difference is that the tournament layer was
built fast, in one sitting, on top of an id (`pod_id`) that felt like an
internal detail. It was reaching the client and coming back trusted.

## Known gaps, carried deliberately

1. **No off-host backup.** The largest real risk. Deferred with a trigger above.
2. **Email recovery is stored but not implemented.** Signup now collects an
   optional address, which raises the stakes on this: the copy is careful to
   say the codes are the only way back in, but the longer an address is stored
   without the feature existing, the more it reads as a promise. Owner: Ben.
   Trigger: implement it or stop collecting it before the first outside user.
3. **The tournament layer is unlogged.** The audit's "no application logging at
   all" finding is largely closed — `security_log` now records auth failures,
   admin denials, rate-limit trips and bans. `tournaments.py` is the exception:
   it does not import `audit`, so every authorization denial it raises is
   silent. That is precisely the layer the 2026-07-19 audit found five defects
   in, so a sixth being probed would look like nothing at all. Owner: Ben.
   Trigger: before the app is used for an event with stakes.
4. **Failures are swallowed in three places.** `broadcast` (`table.py`) uses a
   bare `except Exception: pass`; so does the limiter's audit write, annotated
   and deliberate so logging cannot break the limiter. The third is the
   concerning one: `get_state` in `tournaments.py` swallows any failure of
   `current_account()` and silently downgrades the caller to non-organizer —
   which turns a genuine auth bug into what looks like a permissions decision.
   Fails closed, so it is not a vulnerability; it is a debugging trap.
5. **Security headers are set by the app but unverified end-to-end.** `main.py`
   sets a Permissions-Policy. CSP, HSTS, X-Content-Type-Options and
   Referrer-Policy depend on Caddy, whose config is not in this repo, so the
   served response has not been confirmed. Referrer-Policy matters directly for
   the next item.
6. **Entrant tokens ride in query strings**, so the reverse proxy must strip
   query parameters from access logs. That coupling is invisible from either
   file; a header would remove it. Tracked in `docs/ideas.md`.

Each of these is a decision, not an oversight. The distinction matters: a gap
someone chose and wrote down can be reviewed, and a gap nobody noticed cannot.
