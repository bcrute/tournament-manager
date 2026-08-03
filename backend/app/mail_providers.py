"""Named email providers, so switching one out is a word rather than a rewrite.

Every provider worth using speaks SMTP, so this is a registry of settings
rather than a stack of API clients. That is a deliberate choice and worth
defending: an HTTP adapter per provider would be a bespoke request shape, a
bespoke error shape and a bespoke auth scheme each, all to send a two-line
plain-text message that SMTP already sends. The thing that actually differs
between providers is four values — host, port, TLS flavour, and what they
expect in the username field — and three of those are the ones people get
wrong.

So: `TABLE_MAIL_PROVIDER=fastmail`, a key, a from-address, done. Anything not
listed here still works through `TABLE_SMTP_HOST` directly; the registry is a
convenience over that path, never a gate in front of it.

Two kinds of entry, and the distinction is the useful part:

- **mailbox** — send through an email account you already have, using its
  submission endpoint. No new service, no new quota, nobody new learning who is
  recovering an account. This is what "send our own email without running a
  mail server" actually means in practice, and for this deployment it is also
  the least work: `skadoosh.dev` already has Fastmail MX, SPF and DKIM records
  published, so mail from an `@skadoosh.dev` address through Fastmail passes
  authentication today with no DNS changes at all.
- **transactional** — a service built for application mail. Worth moving to if
  the volume ever justifies it, which for two account-recovery messages per
  user it does not.

What is *not* an option: delivering straight to recipients' mail servers from
the app's own host. It needs outbound port 25 (blocked by most VPS providers),
a PTR record on the sending IP (74.208.222.65 has none), and a warmed sender
reputation — and the failure mode is silent spam-foldering of exactly the
messages someone locked out of their account is waiting for.

**The `username_is` field is the point.** Half of these do not want your
account's login in the SMTP username. Resend wants the literal string
`resend`. SendGrid wants the literal string `apikey`. Getting that wrong
produces an authentication failure that reads as a bad password, and people
lose an afternoon to it.

A **transactional** provider additionally needs the sender domain verified
before it will deliver anything — DNS records on the domain in
`TABLE_MAIL_FROM`. There is no way around that and it is not a bug: it is what
stops anyone else sending as your domain. Budget for it being the slow part of
setup, not the code. A **mailbox** provider needs none of that when the domain
already receives mail there, because the records are the ones already making
that work.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    #: "mailbox" — send through an email account you already have, using its
    #: submission endpoint. No new service, no new quota, and the provider is
    #: one you already trust with your mail.
    #: "transactional" — a service that exists to send application mail. More
    #: headroom and better bounce handling; another company learning who is
    #: recovering an account.
    kind: str
    host: str
    port: int
    #: "starttls" (587, the common case) or "implicit" (465, TLS from the
    #: first byte). Sending STARTTLS on an implicit-TLS connection is an
    #: error, not a belt-and-braces, which is why this is explicit.
    tls: str
    #: What goes in the SMTP username. Free text because the interesting cases
    #: are the ones where it is not "your account".
    username_is: str
    #: Where the credential comes from, so a person setting this up on a phone
    #: at a game store has somewhere to go.
    credentials_at: str
    #: Free tier, as advertised when this was written (2026-08-03). Verify
    #: before relying on it — these change, and a stale number in a comment is
    #: worse than none.
    free_tier: str
    #: Where the company is and whose law it answers to. This is why the
    #: registry has a comment column at all.
    jurisdiction: str
    notes: str = ""


#: Ordered by how much they are worth recommending, most first. The order is
#: read by `describe()` and by nothing else.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key="fastmail",
        kind="mailbox",
        name="Fastmail",
        host="smtp.fastmail.com",
        # Implicit TLS from the first byte. 587 with STARTTLS also works, but
        # 465 is the one that cannot be downgraded by something in the middle.
        port=465,
        tls="implicit",
        username_is="your full Fastmail address, and an APP PASSWORD (not your login password) with SMTP access",
        credentials_at="https://app.fastmail.com/settings/security/apps",
        free_tier="included in the mailbox you already pay for — no separate quota",
        jurisdiction="Australia — no ads, no scanning; independent of the big platforms",
        notes=(
            "The right answer for this deployment, verified rather than "
            "assumed: skadoosh.dev's MX already points at Fastmail, SPF "
            "already includes spf.messagingengine.com, and the fm1/fm2/fm3 "
            "DKIM records are already published. Mail sent from an "
            "@skadoosh.dev address through Fastmail therefore passes SPF and "
            "DKIM today, with no new account, no new DNS, and no third party "
            "learning who is recovering an account. Daily limits exist and are "
            "far above what two account-recovery messages per user will ever "
            "reach; check their current sending policy if that stops being "
            "true."
        ),
    ),
    Provider(
        key="google",
        kind="mailbox",
        name="Gmail / Google Workspace",
        host="smtp.gmail.com",
        port=465,
        tls="implicit",
        username_is="your full Gmail address, and an APP PASSWORD (requires 2-step verification)",
        credentials_at="https://myaccount.google.com/apppasswords",
        free_tier="included in the account you already have",
        jurisdiction="United States",
        notes=(
            "The same trick as Fastmail, if that is where the domain's mail "
            "lives. Sending appears in your own Sent folder, which is either "
            "useful or annoying."
        ),
    ),
    Provider(
        key="migadu",
        kind="mailbox",
        name="Migadu",
        host="smtp.migadu.com",
        port=465,
        tls="implicit",
        username_is="the full address of a mailbox you created",
        credentials_at="https://admin.migadu.com/",
        free_tier="included in the plan; Migadu prices by domain, not by message",
        jurisdiction="Switzerland",
        notes="The other privacy-minded mailbox host worth naming.",
    ),
    Provider(
        key="brevo",
        kind="transactional",
        name="Brevo",
        host="smtp-relay.brevo.com",
        port=587,
        tls="starttls",
        username_is="the login email of your Brevo account",
        credentials_at="https://app.brevo.com/settings/keys/smtp",
        free_tier="300 emails/day, no card required",
        jurisdiction="France (EU) — GDPR-native, EU data residency",
        notes=(
            "The transactional one to pick if the mailbox route is ever "
            "outgrown or unavailable. EU-hosted and answerable to EU data "
            "protection law directly rather than through an adequacy decision "
            "that can be withdrawn, which is the privacy difference that "
            "actually bites; 300 a day is free permanently and needs no card, "
            "so at two messages per user there is no path to a bill."
        ),
    ),
    Provider(
        key="mailjet",
        kind="transactional",
        name="Mailjet",
        host="in-v3.mailjet.com",
        port=587,
        tls="starttls",
        username_is="your Mailjet API key (not an email address)",
        credentials_at="https://app.mailjet.com/account/apikeys",
        free_tier="200 emails/day, 6,000/month",
        jurisdiction="France (EU), owned by Sinch (Sweden) — GDPR, EU hosting",
        notes=(
            "The other EU option, and the fallback if Brevo's signup will not "
            "take you. Username is the API key and password is the secret "
            "key — neither is your account login."
        ),
    ),
    Provider(
        key="resend",
        kind="transactional",
        name="Resend",
        host="smtp.resend.com",
        port=587,
        tls="starttls",
        username_is="the literal string 'resend'",
        credentials_at="https://resend.com/api-keys",
        free_tier="3,000 emails/month, 100/day",
        jurisdiction="United States",
        notes=(
            "The least setup friction of any of these, and the one to pick if "
            "you want it working in ten minutes. US-hosted, so it is the "
            "weaker choice on the axis you asked about."
        ),
    ),
    Provider(
        key="postmark",
        kind="transactional",
        name="Postmark",
        host="smtp.postmarkapp.com",
        port=587,
        tls="starttls",
        username_is="your Postmark server API token (used as both user and password)",
        credentials_at="https://account.postmarkapp.com/servers",
        free_tier="100 emails/month",
        jurisdiction="United States (ActiveCampaign)",
        notes=(
            "Best deliverability reputation of the list — worth knowing if "
            "reset links start landing in spam elsewhere. The free tier is "
            "small but this app's volume is two messages per user, ever."
        ),
    ),
    Provider(
        key="sendgrid",
        kind="transactional",
        name="SendGrid",
        host="smtp.sendgrid.net",
        port=587,
        tls="starttls",
        username_is="the literal string 'apikey'",
        credentials_at="https://app.sendgrid.com/settings/api_keys",
        free_tier="100 emails/day",
        jurisdiction="United States (Twilio)",
        notes="Listed because it is everywhere, not because it is the best of these.",
    ),
    Provider(
        key="smtp2go",
        kind="transactional",
        name="SMTP2GO",
        host="mail.smtp2go.com",
        port=587,
        tls="starttls",
        username_is="the SMTP username you create in their console",
        credentials_at="https://app.smtp2go.com/settings/users",
        free_tier="1,000 emails/month",
        jurisdiction="New Zealand, with EU/UK region options",
        notes="Region-selectable, which is unusual on a free tier.",
    ),
)

BY_KEY = {p.key: p for p in PROVIDERS}

#: The one to use absent a reason. See its `notes` — for this deployment the
#: domain's mail already lives at Fastmail, which makes "send it ourselves,
#: through the mailbox we already have" strictly less machinery than signing up
#: for a transactional service.
RECOMMENDED = "fastmail"

#: What to reach for if the mailbox route is ever outgrown — which for two
#: messages per user is not a near-term concern.
RECOMMENDED_TRANSACTIONAL = "brevo"


class UnknownProvider(ValueError):
    """Raised at startup rather than at send time. A typo in a provider name
    should not surface as an inexplicable delivery failure three days later."""


def resolve(key: str) -> Provider:
    normalised = (key or "").strip().lower()
    if normalised in BY_KEY:
        return BY_KEY[normalised]
    raise UnknownProvider(
        f"unknown mail provider {key!r} — known providers are "
        + ", ".join(BY_KEY)
        + ". For anything else, set TABLE_SMTP_HOST directly instead."
    )


def describe(key: str | None = None) -> str:
    """Human-readable setup notes. Printed by `scripts/mailcheck`, and the
    reason the registry carries prose at all: the failure mode here is a person
    with the right password in the wrong field."""
    chosen = [resolve(key)] if key else list(PROVIDERS)
    lines = []
    last_kind = None
    for p in chosen:
        if key is None and p.kind != last_kind:
            last_kind = p.kind
            lines += [
                {
                    "mailbox": "-- Send it yourself, through a mailbox you already have --",
                    "transactional": "-- Or use a service built for application mail --",
                }[p.kind],
                "",
            ]
        lines += [
            f"{p.name}  (TABLE_MAIL_PROVIDER={p.key})",
            f"  host          {p.host}:{p.port} ({p.tls})",
            f"  free tier     {p.free_tier}",
            f"  jurisdiction  {p.jurisdiction}",
            f"  SMTP user     {p.username_is}",
            f"  credentials   {p.credentials_at}",
        ]
        if p.notes:
            lines.append(f"  notes         {p.notes}")
        lines.append("")
    return "\n".join(lines)
