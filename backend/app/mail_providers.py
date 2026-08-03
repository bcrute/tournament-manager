"""Named email providers, so switching one out is a word rather than a rewrite.

Every provider worth using speaks SMTP, so this is a registry of settings
rather than a stack of API clients. That is a deliberate choice and worth
defending: an HTTP adapter per provider would be a bespoke request shape, a
bespoke error shape and a bespoke auth scheme each, all to send a two-line
plain-text message that SMTP already sends. The thing that actually differs
between providers is four values — host, port, TLS flavour, and what they
expect in the username field — and three of those are the ones people get
wrong.

So: `TABLE_MAIL_PROVIDER=brevo`, a key, a from-address, done. Anything not
listed here still works through `TABLE_SMTP_HOST` directly; the registry is a
convenience over that path, never a gate in front of it.

**The `username_is` field is the point.** Half of these do not want your
account's login in the SMTP username. Resend wants the literal string
`resend`. SendGrid wants the literal string `apikey`. Getting that wrong
produces an authentication failure that reads as a bad password, and people
lose an afternoon to it.

Every one of these also requires a **verified sender** before it will deliver
anything — usually DNS records (SPF, and DKIM) on the domain in
`TABLE_MAIL_FROM`. There is no way around that and it is not a bug: it is what
stops anyone else sending as your domain. Budget for it being the slow part of
setup, not the code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
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
        key="brevo",
        name="Brevo",
        host="smtp-relay.brevo.com",
        port=587,
        tls="starttls",
        username_is="the login email of your Brevo account",
        credentials_at="https://app.brevo.com/settings/keys/smtp",
        free_tier="300 emails/day, no card required",
        jurisdiction="France (EU) — GDPR-native, EU data residency",
        notes=(
            "The recommended default. EU-hosted and answerable to EU data "
            "protection law rather than adequacy decisions, which is the "
            "privacy difference that actually bites; the free tier is also "
            "the most generous of the EU options by a wide margin. This app "
            "sends two message types and only when a user asks, so 300 a day "
            "is not a constraint it will ever notice."
        ),
    ),
    Provider(
        key="mailjet",
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

#: The one to use absent a reason. See its `notes`.
RECOMMENDED = "brevo"


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
    for p in chosen:
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
