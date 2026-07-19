# Security decisions

This project's answers to the checklist in the security reference
(`governance/security_open_questions.md`). The reference asks the questions;
this file records what *this* project decided and why.

Rules from the reference that apply here: a decision without a rationale is
only an assertion; "deferred" needs an owner and a trigger; sections that don't
apply are marked not-applicable explicitly rather than deleted.

Owner for everything below: Ben. Last reviewed 2026-07-19 (post-audit).

---

## What this project is, in security terms

An anonymous-first app for tabletop game nights and tournaments. The defining
decision — which most of the rest follows from — is that **playing requires no
account and no personal data**. A player supplies a display name they choose,
and nothing else. Accounts are optional and exist only for history and notes;
the sole exception is tournament organizers, who need a recovery email because
losing access mid-event strands every table.

The practical consequence is that **most data-protection questions are answered
by not having the data**. That is a deliberate control, not an accident of
scope, and it should survive future features (see `docs/ideas.md`, "Identity").

---

## Authentication

| Question | Decision | Rationale |
| --- | --- | --- |
| Session timeout | Account sessions expire server-side; the cookie is httpOnly, Secure, SameSite. | Sessions are a convenience over an optional account, not access to sensitive data. |
| Second-factor recovery | No second factor. Recovery is 8 single-use codes, shown once at signup, plus an optional email. | Requiring MFA on an optional account for a game-night app would cost more accounts than it protects. Recovery codes work without collecting an address. |
| Identity provider dependency | None — no external IdP. | No third-party dependency to be unavailable. |
| Break-glass access | None. There is no administrative UI or role. | Nothing to break into; server access is SSH-only, key-only. |
| Strong authenticators | Not supported. | See second-factor recovery. |
| Bootstrap/first admin | Not applicable — no admin accounts exist. | The app has no privileged user class. |

**Player and entrant credentials** are bearer tokens, not accounts:

- room token (`X-Player-Token`) — one seat in one room
- entrant token (`?token=`) — one seat in one tournament

Both are `secrets.token_urlsafe(24)`. They are capability tokens: possession is
the authorization, and they grant nothing outside their room or tournament.

---

## Authorization

| Question | Decision | Rationale |
| --- | --- | --- |
| Role model | Three implicit roles: organizer (owns a tournament), player (holds a token), anonymous. Permissions are additive from nothing. | No role can be over-privileged by default because there is no default grant. |
| Custom roles | Not supported. | No demand, and a role editor is a large attack surface for a game app. |
| Sensitive export | No bulk export exists. | Nothing to export — see data minimisation. |
| Access review cadence | Not applicable — no standing administrative access. | |
| Separation of duties | An organizer both runs and rules on their own event. Accepted. | Inherent to a one-person tournament; the alternative is requiring two staff, which the target user doesn't have. Results are versioned so an override leaves a trail. |

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

| Question | Decision | Rationale |
| --- | --- | --- |
| Audit immutability | Game events are append-only in practice but not enforced at the database level. Accepted. | The audit consumer is a player wondering who killed them, not a regulator. Hash chaining would be theatre here. |
| Audit granularity | Game events record actor, action, target and timestamp. Result changes are versioned with source (`auto` vs `organizer`) and a note. | An organizer overriding a result is the one action with real consequences, so it keeps history rather than mutating. |
| Audit retention | Tied to the room's lifetime; account history persists until the account is deleted. | |
| Denial logging | **Gap.** Authorization denials are not logged distinctly from other 4xx. | Recorded rather than hidden; low priority while the app has no admin surface to attack. |

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
2. **Email recovery is stored but not implemented.** See above.
3. **No application logging at all.** There is no `import logging` anywhere in
   `backend/app/`: no authorization denial, authentication failure, ban, or
   rate-limit trip is recorded, and `broadcast` swallows exceptions with a bare
   `except Exception: pass`. The audit rated this Medium. It is the largest
   remaining gap now that the authorization defects are closed — an attacker
   probing this app leaves no trace. Owner: Ben. Trigger: before the app is
   used for an event with stakes.
4. **Security headers are unverified.** CSP, HSTS, X-Content-Type-Options and
   Referrer-Policy are not set by the application. Caddy may set them, but the
   Caddyfile is not in this repo so it could not be confirmed. Referrer-Policy
   matters directly for the next item.
5. **Entrant tokens ride in query strings**, so the reverse proxy must strip
   query parameters from access logs. That coupling is invisible from either
   file; a header would remove it. Tracked in `docs/ideas.md`.

Each of these is a decision, not an oversight. The distinction matters: a gap
someone chose and wrote down can be reviewed, and a gap nobody noticed cannot.
