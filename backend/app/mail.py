"""Outbound email, and the seam that lets it not exist.

This app sent no email at all until 2026-08-02, and that was a documented gap
rather than a design: an address was collected and stored, nothing was ever
sent to it, and the recovery codes were the only path back into an account.
Storing an address that implies a capability the app lacks is the half-built
promise `docs/security.md` names.

Three transports, one interface:

- **smtp** — the real one. Selected by configuring `TABLE_SMTP_HOST`.
- **console** — writes the message to stdout. For development, and it must be
  asked for explicitly (`TABLE_MAIL_CONSOLE=1`), because a password-reset link
  in a container log on a real deployment is a credential in a log.
- **off** — the default when nothing is configured. Every send raises, and the
  routes that would send turn that into a 503 saying so.

`off` being the default is the point. The alternative — silently swallowing
sends on an unconfigured deployment — produces an account-recovery flow that
appears to work, tells the user to check their inbox, and never delivers. A
503 is worse to look at and better to be.

Tests use `FakeMailer`, which records rather than sends. It is a first-class
transport, not a mock: the routes under test go through exactly the code path
production goes through, up to the last inch.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage


class MailNotConfigured(RuntimeError):
    """No transport. Raised at send time, not at import — a deployment that
    never sends email is a supported deployment, it just cannot host."""


@dataclass
class Message:
    to: str
    subject: str
    body: str


class Mailer:
    """The whole interface. Deliberately one method: everything this app sends
    is a short plain-text message with a link in it, and a richer transport
    would be a richer thing to get wrong."""

    def send(self, message: Message) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class OffMailer(Mailer):
    def send(self, message: Message) -> None:
        raise MailNotConfigured(
            "no mail transport is configured on this deployment"
        )


@dataclass
class FakeMailer(Mailer):
    """Records instead of sending. Used by the tests, and by nothing else."""

    sent: list[Message] = field(default_factory=list)

    def send(self, message: Message) -> None:
        self.sent.append(message)

    def last_to(self, address: str) -> Message | None:
        for message in reversed(self.sent):
            if message.to.lower() == address.lower():
                return message
        return None

    def clear(self) -> None:
        self.sent.clear()


@dataclass
class ConsoleMailer(Mailer):
    """Prints the message. The one place this project writes to stdout on
    purpose — see `AGENTS.md` on why there is no `logging` in `app/`: that rule
    is about durable application logs, and a development mail transport whose
    entire job is to be read by a human at a terminal is the opposite case."""

    def send(self, message: Message) -> None:
        print(
            f"\n--- mail (console transport) ---\n"
            f"To: {message.to}\nSubject: {message.subject}\n\n{message.body}\n"
            f"--- end mail ---\n",
            flush=True,
        )


@dataclass
class SmtpMailer(Mailer):
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    use_tls: bool = True

    def send(self, message: Message) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.body)
        # STARTTLS on 587 is the common case; implicit TLS on 465 is the other.
        if self.port == 465:
            with smtplib.SMTP_SSL(
                self.host, self.port, context=ssl.create_default_context(), timeout=20
            ) as server:
                if self.username:
                    server.login(self.username, self.password or "")
                server.send_message(msg)
            return
        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            if self.use_tls:
                server.starttls(context=ssl.create_default_context())
            if self.username:
                server.login(self.username, self.password or "")
            server.send_message(msg)


def build_mailer(env: dict[str, str] | None = None) -> Mailer:
    """Choose a transport from the environment. Pure, so a test can ask what a
    given deployment config would produce without setting real variables."""
    env = os.environ if env is None else env
    host = (env.get("TABLE_SMTP_HOST") or "").strip()
    if host:
        return SmtpMailer(
            host=host,
            port=int(env.get("TABLE_SMTP_PORT") or 587),
            username=(env.get("TABLE_SMTP_USER") or "").strip() or None,
            password=env.get("TABLE_SMTP_PASSWORD") or None,
            sender=(env.get("TABLE_MAIL_FROM") or "").strip()
            or f"no-reply@{host}",
            use_tls=(env.get("TABLE_SMTP_TLS") or "on").lower() != "off",
        )
    if (env.get("TABLE_MAIL_CONSOLE") or "").lower() in ("1", "on", "true", "yes"):
        return ConsoleMailer()
    return OffMailer()


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        _mailer = build_mailer()
    return _mailer


def set_mailer(mailer: Mailer | None) -> None:
    """Install a transport. Tests use it; so would an operator's smoke test."""
    global _mailer
    _mailer = mailer


def mail_configured() -> bool:
    return not isinstance(get_mailer(), OffMailer)


def public_base_url(env: dict[str, str] | None = None) -> str:
    """Where the links in those emails point.

    Required rather than derived from the request: a `Host` header is
    attacker-controlled, and a verification link built from one is a
    password-reset link pointed at somebody else's server. Defaults to the
    deployment this repo actually ships.
    """
    env = os.environ if env is None else env
    return (env.get("TABLE_PUBLIC_URL") or "https://mtg.skadoosh.dev").rstrip("/")
