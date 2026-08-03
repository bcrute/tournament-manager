"""A recovery address that recovers something.

Before 2026-08-02 an address was typed into a box, stored, and never used for
anything — and `hasEmail` was true the moment it was stored, which is what
hosting a tournament rested on. The whole point of requiring an address to host
is that an organizer locked out mid-event strands a room, and an address with a
typo in it is precisely the case where that happens.

So the claim changed: `hasEmail` means somebody clicked a link sent to that
mailbox. These tests are about the two things that follow — that unconfirmed is
treated as absent everywhere it matters, and that the tokens which do the
confirming behave like credentials.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.accounts import RESET_TTL, VERIFY_TTL, _token_hash
from app.accounts import router as accounts_router
from app.db import q
from app.mail import (
    ConsoleMailer,
    MailMisconfigured,
    FakeMailer,
    FileMailer,
    MailNotConfigured,
    Message,
    OffMailer,
    SmtpMailer,
    build_mailer,
    get_mailer,
    public_base_url,
    set_mailer,
)
from app.tournaments import router as tournaments_router
from conftest import mailbox

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(accounts_router, prefix="/api/account")
    app.include_router(tournaments_router, prefix="/api/tournament")
    # the session cookie is Secure, so a client on http would refuse to store it
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def fresh(client):
    client.cookies.clear()
    return client


def signup(c, username, password=PASSWORD):
    return c.post("/api/account/signup", json={"username": username, "password": password})


def link_token(message: Message) -> str:
    """The token out of the link in a message — from the fragment, which is
    where these live."""
    line = next(l for l in message.body.splitlines() if l.startswith("http"))
    return line.split("#", 1)[1]


def enrol(c, username, address, password=PASSWORD):
    """Sign up and add an address, returning the confirmation token."""
    signup(c, username, password)
    r = c.post("/api/account/email", json={"email": address, "password": password})
    assert r.status_code == 200, r.text
    return link_token(mailbox.last_to(address))


# ---------------------------------------------------------------- transports


class TestTheTransportSeam:
    def test_nothing_configured_means_nothing_is_sent(self):
        """Not a silent no-op. A deployment that cannot send mail must say so,
        because the alternative is a recovery flow that tells the user to check
        an inbox nothing will ever arrive in."""
        mailer = build_mailer({})
        assert isinstance(mailer, OffMailer)
        with pytest.raises(MailNotConfigured):
            mailer.send(Message("a@example.com", "s", "b"))

    def test_smtp_is_chosen_by_configuring_a_host(self):
        mailer = build_mailer(
            {
                "TABLE_SMTP_HOST": "smtp.example.com",
                "TABLE_SMTP_PORT": "587",
                "TABLE_SMTP_USER": "postmaster",
                "TABLE_SMTP_PASSWORD": "hunter2",
                "TABLE_MAIL_FROM": "Lifetap <no-reply@example.com>",
            }
        )
        assert isinstance(mailer, SmtpMailer)
        assert (mailer.host, mailer.port) == ("smtp.example.com", 587)
        assert mailer.sender == "Lifetap <no-reply@example.com>"

    def test_a_sender_is_invented_rather_than_left_empty(self):
        mailer = build_mailer({"TABLE_SMTP_HOST": "smtp.example.com"})
        assert "@" in mailer.sender

    def test_the_console_transport_must_be_asked_for(self):
        """It prints reset links to stdout. That is right for development and
        wrong for a deployment, so it never happens by default."""
        assert isinstance(build_mailer({}), OffMailer)
        assert isinstance(build_mailer({"TABLE_MAIL_CONSOLE": "1"}), ConsoleMailer)

    def test_a_file_transport_catches_mail_for_a_browser_test(self, tmp_path):
        """A real transport, the way a local mail catcher is, not a test hook.
        The browser suite reads a confirmation link out of it — the alternative
        was a test-only way to skip confirming, which would leave the flow most
        in need of end-to-end coverage covered only by unit tests."""
        import json

        path = tmp_path / "mail.jsonl"
        mailer = build_mailer({"TABLE_MAIL_FILE": str(path)})
        assert isinstance(mailer, FileMailer)
        mailer.send(Message("who@example.com", "Subject", "line one\nhttps://x/#tok"))
        mailer.send(Message("other@example.com", "Second", "body"))
        written = [json.loads(l) for l in path.read_text().splitlines()]
        assert [m["to"] for m in written] == ["who@example.com", "other@example.com"]
        assert "https://x/#tok" in written[0]["body"]

    def test_smtp_wins_over_every_other_choice(self):
        mailer = build_mailer({
            "TABLE_SMTP_HOST": "smtp.example.com",
            "TABLE_MAIL_CONSOLE": "1",
            "TABLE_MAIL_FILE": "/tmp/nope.jsonl",
        })
        assert isinstance(mailer, SmtpMailer)

    def test_the_tests_run_on_a_real_transport(self):
        """`FakeMailer` records; it does not stub out the route. Everything
        below goes through the same code production goes through."""
        assert isinstance(get_mailer(), FakeMailer)

    def test_links_are_built_from_configuration_not_the_request(self):
        """A `Host` header is attacker-controlled. A password-reset link built
        from one points wherever the attacker said."""
        assert public_base_url({}).startswith("https://")
        assert public_base_url({"TABLE_PUBLIC_URL": "https://x.example/"}) == "https://x.example"


class TestTheTransportsThemselves:
    """The two real transports, exercised without a network.

    `SmtpMailer` is the one piece of this feature that cannot be tested against
    the thing it talks to, so the parts worth pinning are the parts that are
    decisions rather than plumbing: which port implies which flavour of TLS,
    that credentials are only offered when configured, and that the message is
    assembled the way a mail server expects.
    """

    def test_the_console_transport_prints_the_whole_message(self, capsys):
        ConsoleMailer().send(Message("who@example.com", "A subject", "the body"))
        printed = capsys.readouterr().out
        assert "who@example.com" in printed
        assert "A subject" in printed
        assert "the body" in printed

    def fake_smtp(self, monkeypatch, attr):
        """Replace one smtplib entry point and record what it was asked to do."""
        import smtplib

        calls = {"init": None, "starttls": 0, "login": None, "sent": None}

        class Server:
            def __init__(self, host, port, **kw):
                calls["init"] = (host, port)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def starttls(self, **kw):
                calls["starttls"] += 1

            def login(self, user, password):
                calls["login"] = (user, password)

            def send_message(self, msg):
                calls["sent"] = msg

        monkeypatch.setattr(smtplib, attr, Server)
        return calls

    def test_port_587_starts_tls_and_logs_in(self, monkeypatch):
        calls = self.fake_smtp(monkeypatch, "SMTP")
        SmtpMailer("smtp.example.com", 587, "postmaster", "hunter2",
                   "no-reply@example.com").send(
            Message("who@example.com", "Subject here", "Body here")
        )
        assert calls["init"] == ("smtp.example.com", 587)
        assert calls["starttls"] == 1
        assert calls["login"] == ("postmaster", "hunter2")
        assert calls["sent"]["To"] == "who@example.com"
        assert calls["sent"]["From"] == "no-reply@example.com"
        assert calls["sent"]["Subject"] == "Subject here"
        assert "Body here" in calls["sent"].get_content()

    def test_port_465_is_implicit_tls_and_never_calls_starttls(self, monkeypatch):
        """Calling STARTTLS on an already-encrypted connection is an error, not
        a belt-and-braces."""
        calls = self.fake_smtp(monkeypatch, "SMTP_SSL")
        SmtpMailer("smtp.example.com", 465, "postmaster", "hunter2",
                   "no-reply@example.com").send(Message("who@example.com", "s", "b"))
        assert calls["init"] == ("smtp.example.com", 465)
        assert calls["starttls"] == 0
        assert calls["login"] == ("postmaster", "hunter2")

    def test_an_unauthenticated_relay_is_not_offered_a_login(self, monkeypatch):
        """A local relay with no credentials is a normal deployment; sending
        LOGIN with an empty username to one is an error."""
        calls = self.fake_smtp(monkeypatch, "SMTP")
        SmtpMailer("localhost", 25, None, None, "no-reply@example.com", use_tls=False).send(
            Message("who@example.com", "s", "b")
        )
        assert calls["login"] is None
        assert calls["starttls"] == 0
        assert calls["sent"] is not None


class TestNamedProviders:
    """`TABLE_MAIL_PROVIDER=brevo` instead of four variables copied off a docs
    page. The registry is a convenience over SMTP, so the things worth pinning
    are that it fills in the right values, that it never blocks the raw path,
    and that a misconfiguration is loud at startup rather than silent until
    somebody forgets their password."""

    def test_a_name_fills_in_host_port_and_tls(self):
        mailer = build_mailer(
            {
                "TABLE_MAIL_PROVIDER": "brevo",
                "TABLE_SMTP_USER": "me@example.com",
                "TABLE_SMTP_PASSWORD": "key",
                "TABLE_MAIL_FROM": "no-reply@example.com",
            }
        )
        assert isinstance(mailer, SmtpMailer)
        assert (mailer.host, mailer.port, mailer.use_tls) == (
            "smtp-relay.brevo.com",
            587,
            True,
        )

    def test_every_registered_provider_builds(self):
        """A typo in the registry is a provider nobody can use."""
        from app.mail_providers import PROVIDERS

        for provider in PROVIDERS:
            mailer = build_mailer(
                {
                    "TABLE_MAIL_PROVIDER": provider.key,
                    "TABLE_SMTP_USER": "u",
                    "TABLE_SMTP_PASSWORD": "p",
                    "TABLE_MAIL_FROM": "no-reply@example.com",
                }
            )
            assert isinstance(mailer, SmtpMailer), provider.key
            assert mailer.host and "." in mailer.host, provider.key
            assert provider.tls in ("starttls", "implicit"), provider.key
            # implicit TLS is port 465 and must not also send STARTTLS
            assert (mailer.port == 465) == (provider.tls == "implicit"), provider.key

    def test_the_name_is_case_and_space_insensitive(self):
        for spelling in ("Brevo", " brevo ", "BREVO"):
            mailer = build_mailer(
                {
                    "TABLE_MAIL_PROVIDER": spelling,
                    "TABLE_SMTP_USER": "u",
                    "TABLE_SMTP_PASSWORD": "p",
                    "TABLE_MAIL_FROM": "f@example.com",
                }
            )
            assert mailer.host == "smtp-relay.brevo.com", spelling

    def test_a_typo_names_the_alternatives_rather_than_guessing(self):
        from app.mail_providers import UnknownProvider

        with pytest.raises(UnknownProvider) as caught:
            build_mailer({"TABLE_MAIL_PROVIDER": "brevoo", "TABLE_SMTP_PASSWORD": "p"})
        message = str(caught.value)
        assert "brevo" in message and "mailjet" in message
        assert "TABLE_SMTP_HOST" in message, "the escape hatch has to be discoverable"

    @pytest.mark.parametrize(
        "missing,expected",
        [
            ("TABLE_SMTP_PASSWORD", "TABLE_SMTP_PASSWORD"),
            ("TABLE_SMTP_USER", "TABLE_SMTP_USER"),
            ("TABLE_MAIL_FROM", "TABLE_MAIL_FROM"),
        ],
    )
    def test_half_a_configuration_fails_at_startup_not_at_send_time(self, missing, expected):
        """Silence here is a deployment that looks healthy until the first
        person needs it."""
        env = {
            "TABLE_MAIL_PROVIDER": "brevo",
            "TABLE_SMTP_USER": "u",
            "TABLE_SMTP_PASSWORD": "p",
            "TABLE_MAIL_FROM": "f@example.com",
        }
        del env[missing]
        with pytest.raises(MailMisconfigured) as caught:
            build_mailer(env)
        assert expected in str(caught.value)

    def test_a_missing_credential_says_where_to_get_one(self):
        with pytest.raises(MailMisconfigured) as caught:
            build_mailer({"TABLE_MAIL_PROVIDER": "resend"})
        assert "resend.com" in str(caught.value)

    def test_a_missing_username_says_what_that_provider_wants_in_it(self):
        """The single most common way to get this wrong: Resend wants the
        literal string 'resend' there, not an account name, and a wrong value
        fails as though the password were bad."""
        with pytest.raises(MailMisconfigured) as caught:
            build_mailer({"TABLE_MAIL_PROVIDER": "resend", "TABLE_SMTP_PASSWORD": "p"})
        assert "resend" in str(caught.value).lower()

    def test_no_sender_is_ever_invented_for_a_provider(self):
        """The raw-host path guesses `no-reply@<host>` because a local relay
        will accept it. No provider here will: they all refuse to deliver from
        an unverified address, so a guess is a guaranteed bounce wearing the
        costume of a working config."""
        with pytest.raises(MailMisconfigured):
            build_mailer(
                {
                    "TABLE_MAIL_PROVIDER": "brevo",
                    "TABLE_SMTP_USER": "u",
                    "TABLE_SMTP_PASSWORD": "p",
                }
            )

    def test_an_explicit_host_wins_over_a_named_provider(self):
        """The registry must never be a gate in front of plain SMTP. Someone
        who typed a host means it — a self-hosted relay, or a provider that
        isn't listed."""
        mailer = build_mailer(
            {
                "TABLE_MAIL_PROVIDER": "brevo",
                "TABLE_SMTP_HOST": "smtp.myown.example",
                "TABLE_SMTP_PASSWORD": "p",
            }
        )
        assert mailer.host == "smtp.myown.example"

    def test_a_port_can_still_be_overridden(self):
        """Some networks block 587."""
        mailer = build_mailer(
            {
                "TABLE_MAIL_PROVIDER": "brevo",
                "TABLE_SMTP_PORT": "2525",
                "TABLE_SMTP_USER": "u",
                "TABLE_SMTP_PASSWORD": "p",
                "TABLE_MAIL_FROM": "f@example.com",
            }
        )
        assert mailer.port == 2525

    def test_naming_no_provider_still_means_off(self):
        """Adding the registry must not have made an unconfigured deployment
        start claiming it can send."""
        assert isinstance(build_mailer({}), OffMailer)
        assert isinstance(build_mailer({"TABLE_MAIL_PROVIDER": ""}), OffMailer)

    def test_the_recommendation_is_one_of_the_listed_providers(self):
        from app.mail_providers import BY_KEY, RECOMMENDED

        assert RECOMMENDED in BY_KEY

    def test_the_setup_notes_say_the_things_people_get_wrong(self):
        """`describe()` exists because the failure is a person with the right
        password in the wrong field. If it stops saying so, it stops earning
        its place."""
        from app.mail_providers import describe

        text = describe()
        for provider in ("brevo", "resend", "sendgrid"):
            assert f"TABLE_MAIL_PROVIDER={provider}" in text
        assert "apikey" in text, "SendGrid's literal username is the classic trap"
        assert "https://" in text, "somewhere to actually get the credential"

    def test_describing_one_provider_describes_only_that_one(self):
        from app.mail_providers import describe

        assert "Brevo" in describe("brevo")
        assert "SendGrid" not in describe("brevo")


class TestWhenMailCannotBeSent:
    def test_enrolling_an_address_says_so_rather_than_pretending(self, fresh):
        signup(fresh, "nomail.one")
        set_mailer(OffMailer())
        try:
            r = fresh.post("/api/account/email",
                           json={"email": "n1@example.com", "password": PASSWORD})
            assert r.status_code == 503
            assert "recovery codes" in r.json()["detail"]
        finally:
            set_mailer(mailbox)
        # and nothing was stored, so nothing claims to be pending
        assert fresh.get("/api/account/me").json()["account"]["emailPending"] is False

    def test_forgetting_a_password_still_answers_the_same_way(self, fresh):
        """The enumeration-safe answer cannot start depending on deployment
        configuration — that would make the deployment itself the oracle."""
        signup(fresh, "nomail.two")
        set_mailer(OffMailer())
        try:
            r = fresh.post("/api/account/forgot", json={"username": "nomail.two"})
            assert r.status_code == 200
            assert r.json()["ok"] is True
        finally:
            set_mailer(mailbox)


# ------------------------------------------------------------- confirmation


class TestEnrollingAnAddress:
    def test_the_password_is_required(self, fresh):
        """The recovery address is what hands an account to whoever holds it.
        Pointing it somewhere else is a takeover step, not a preference — same
        reasoning as the username change."""
        signup(fresh, "enrol.pw")
        r = fresh.post("/api/account/email",
                       json={"email": "e@example.com", "password": "not the password"})
        assert r.status_code == 403
        row = q("SELECT email FROM accounts WHERE username = ?", ("enrol.pw",)).fetchone()
        assert row["email"] is None

    def test_a_wrong_password_is_recorded_without_the_address(self, fresh):
        signup(fresh, "enrol.logged")
        fresh.post("/api/account/email",
                   json={"email": "secret@example.com", "password": "wrong entirely"})
        rows = q("SELECT subject, detail FROM security_log WHERE kind = 'auth.fail' "
                 "ORDER BY id DESC LIMIT 5").fetchall()
        assert any(r["subject"] == "enrol.logged" and r["detail"] == "email-change" for r in rows)
        assert not any("secret@example.com" in (r["detail"] or "") for r in rows)

    def test_the_address_is_stored_unconfirmed(self, fresh):
        signup(fresh, "enrol.pending")
        r = fresh.post("/api/account/email",
                       json={"email": "pending@example.com", "password": PASSWORD})
        assert r.json()["hasEmail"] is False
        assert r.json()["emailPending"] is True

    def test_a_message_goes_to_the_address_that_was_given(self, fresh):
        signup(fresh, "enrol.sent")
        fresh.post("/api/account/email",
                   json={"email": "Sent@Example.com", "password": PASSWORD})
        message = mailbox.last_to("sent@example.com")
        assert message is not None
        assert "enrol.sent" in message.body

    def test_the_link_carries_the_token_in_a_fragment(self, fresh):
        """Same reasoning as a room invitation: a fragment is never transmitted
        to a server, so a credential in an emailed link cannot land in an access
        log — ours, or a mail gateway's link-rewriter."""
        signup(fresh, "enrol.fragment")
        fresh.post("/api/account/email",
                   json={"email": "frag@example.com", "password": PASSWORD})
        line = next(
            l for l in mailbox.last_to("frag@example.com").body.splitlines()
            if l.startswith("http")
        )
        assert "#" in line
        assert "?" not in line, "a query string is logged; a fragment is not"
        assert line.split("#")[0].endswith("/account/verify")

    def test_the_token_is_stored_only_as_a_hash(self, fresh):
        token = enrol(fresh, "enrol.hashed", "hashed@example.com")
        rows = q("SELECT token_hash FROM email_verifications").fetchall()
        assert all(r["token_hash"] != token for r in rows)
        assert any(r["token_hash"] == _token_hash(token) for r in rows)

    def test_junk_is_refused_before_anything_is_sent(self, fresh):
        signup(fresh, "enrol.junk")
        before = len(mailbox.sent)
        for junk in ("nope", "a@b", "no domain@", "@example.com", "two@@example.com"):
            r = fresh.post("/api/account/email", json={"email": junk, "password": PASSWORD})
            assert r.status_code == 400, junk
        assert len(mailbox.sent) == before

    def test_replacing_an_address_retires_the_old_link(self, fresh):
        """A link forwarded, or sitting in an inbox the owner no longer
        controls, stops working the moment they choose a different address."""
        first = enrol(fresh, "enrol.replaced", "old@example.com")
        fresh.post("/api/account/email", json={"email": "new@example.com", "password": PASSWORD})
        assert fresh.post("/api/account/email/verify", json={"token": first}).status_code == 400

    def test_asking_again_retires_the_previous_link(self, fresh):
        first = enrol(fresh, "enrol.reasked", "reask@example.com")
        fresh.post("/api/account/email/resend")
        second = link_token(mailbox.last_to("reask@example.com"))
        assert second != first
        assert fresh.post("/api/account/email/verify", json={"token": first}).status_code == 400
        assert fresh.post("/api/account/email/verify", json={"token": second}).status_code == 200


class TestConfirming:
    def test_a_valid_link_confirms_it(self, fresh):
        token = enrol(fresh, "confirm.ok", "ok@example.com")
        r = fresh.post("/api/account/email/verify", json={"token": token})
        assert r.status_code == 200
        assert r.json()["hasEmail"] is True
        assert r.json()["emailPending"] is False

    def test_no_session_is_needed(self, fresh):
        """The link is opened from an inbox, which is routinely a different
        device from the one that asked. The token is the authorization."""
        token = enrol(fresh, "confirm.nosession", "nosession@example.com")
        fresh.cookies.clear()
        assert fresh.post("/api/account/email/verify", json={"token": token}).status_code == 200

    def test_it_works_exactly_once(self, fresh):
        token = enrol(fresh, "confirm.once", "once@example.com")
        assert fresh.post("/api/account/email/verify", json={"token": token}).status_code == 200
        assert fresh.post("/api/account/email/verify", json={"token": token}).status_code == 400

    def test_it_expires(self, fresh):
        token = enrol(fresh, "confirm.expired", "expired@example.com")
        q(
            "UPDATE email_verifications SET expires_at = ? WHERE token_hash = ?",
            (int(time.time()) - 1, _token_hash(token)),
        )
        assert fresh.post("/api/account/email/verify", json={"token": token}).status_code == 400

    def test_the_window_is_a_day(self, fresh):
        token = enrol(fresh, "confirm.ttl", "ttl@example.com")
        row = q(
            "SELECT created_at, expires_at FROM email_verifications WHERE token_hash = ?",
            (_token_hash(token),),
        ).fetchone()
        assert row["expires_at"] - row["created_at"] == pytest.approx(VERIFY_TTL, abs=2)

    def test_a_made_up_token_is_refused(self, fresh):
        assert fresh.post("/api/account/email/verify",
                          json={"token": "not-a-real-token-at-all"}).status_code == 400

    def test_expired_and_never_existed_read_the_same(self, fresh):
        """No oracle: someone holding a stolen token must not learn which of
        their guesses was once real."""
        token = enrol(fresh, "confirm.oracle", "oracle@example.com")
        q(
            "UPDATE email_verifications SET expires_at = ? WHERE token_hash = ?",
            (int(time.time()) - 1, _token_hash(token)),
        )
        expired = fresh.post("/api/account/email/verify", json={"token": token})
        invented = fresh.post("/api/account/email/verify", json={"token": "x" * 40})
        assert expired.status_code == invented.status_code == 400
        assert expired.json() == invented.json()

    def test_a_confirmation_cannot_reset_a_password(self, fresh):
        """The two token stores are separate tables, so this is structural
        rather than one forgotten `AND purpose = ?`."""
        token = enrol(fresh, "confirm.crossuse", "crossuse@example.com")
        r = fresh.post("/api/account/reset", json={"token": token, "password": "a whole new one"})
        assert r.status_code == 400


class TestResending:
    def test_it_sends_again(self, fresh):
        enrol(fresh, "resend.ok", "resend@example.com")
        before = len(mailbox.sent)
        assert fresh.post("/api/account/email/resend").json()["sent"] is True
        assert len(mailbox.sent) == before + 1

    def test_it_needs_no_password(self, fresh):
        """It can only ever send to an address the owner already chose, and
        choosing it cost a password."""
        enrol(fresh, "resend.nopw", "resendnopw@example.com")
        assert fresh.post("/api/account/email/resend").status_code == 200

    def test_there_is_nothing_to_resend_without_an_address(self, fresh):
        signup(fresh, "resend.none")
        assert fresh.post("/api/account/email/resend").status_code == 400

    def test_a_confirmed_address_sends_nothing(self, fresh):
        token = enrol(fresh, "resend.done", "resenddone@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        before = len(mailbox.sent)
        assert fresh.post("/api/account/email/resend").json()["sent"] is False
        assert len(mailbox.sent) == before

    def test_signed_out_callers_are_refused(self, fresh):
        assert fresh.post("/api/account/email/resend").status_code == 401


class TestRemoving:
    def test_the_password_is_required(self, fresh):
        token = enrol(fresh, "remove.pw", "removepw@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        r = fresh.post("/api/account/email", json={"email": None, "password": "wrong"})
        assert r.status_code == 403
        assert fresh.get("/api/account/me").json()["account"]["hasEmail"] is True

    def test_it_clears_both_the_address_and_the_confirmation(self, fresh):
        token = enrol(fresh, "remove.ok", "removeok@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        r = fresh.post("/api/account/email", json={"email": None, "password": PASSWORD})
        assert r.json()["hasEmail"] is False
        row = q("SELECT email, email_verified_at FROM accounts WHERE username = ?",
                ("remove.ok",)).fetchone()
        assert row["email"] is None and row["email_verified_at"] is None

    def test_a_live_reset_link_dies_with_the_address(self, fresh):
        """Removing an address is what someone does when it is compromised.
        Leaving a reset link alive would leave the way in that made it worth
        removing."""
        token = enrol(fresh, "remove.reset", "removereset@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        fresh.post("/api/account/forgot", json={"username": "remove.reset"})
        reset = link_token(mailbox.last_to("removereset@example.com"))

        fresh.post("/api/account/email", json={"email": None, "password": PASSWORD})
        r = fresh.post("/api/account/reset", json={"token": reset, "password": "a whole new one"})
        assert r.status_code == 400


# ---------------------------------------------------------------- what it gates


class TestHosting:
    def test_an_unconfirmed_address_does_not_let_you_host(self, fresh):
        """The whole reason hosting needs an address is that a locked-out
        organizer strands a room — and a typo is exactly that case."""
        enrol(fresh, "host.pending", "hostpending@example.com")
        r = fresh.post("/api/tournament", json={"name": "Too Soon"})
        assert r.status_code == 409
        assert "confirm" in r.json()["detail"]

    def test_no_address_at_all_is_the_same_answer(self, fresh):
        signup(fresh, "host.none")
        assert fresh.post("/api/tournament", json={"name": "Nope"}).status_code == 409

    def test_a_confirmed_address_does(self, fresh):
        token = enrol(fresh, "host.confirmed", "hostconfirmed@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        assert fresh.post("/api/tournament", json={"name": "Friday"}).status_code == 200

    def test_removing_the_address_stops_further_hosting(self, fresh):
        token = enrol(fresh, "host.removed", "hostremoved@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        assert fresh.post("/api/tournament", json={"name": "First"}).status_code == 200
        fresh.post("/api/account/email", json={"email": None, "password": PASSWORD})
        assert fresh.post("/api/tournament", json={"name": "Second"}).status_code == 409


class TestTheMigration:
    def test_an_address_from_before_this_feature_counts_as_unconfirmed(self, fresh):
        """Every row already in the database had an address that was typed into
        a box and never checked. Grandfathering those in as confirmed would
        keep making exactly the claim this change stopped making, for the
        accounts most likely to be relying on it."""
        signup(fresh, "legacy.account")
        # what the old code did: an address, and no notion of confirmation
        q("UPDATE accounts SET email = ? WHERE username = ?",
          ("legacy@example.com", "legacy.account"))

        assert fresh.get("/api/account/me").json()["account"]["hasEmail"] is False
        assert fresh.post("/api/tournament", json={"name": "Legacy"}).status_code == 409

    def test_and_the_address_is_still_there_to_confirm(self, fresh):
        """Unverified, not deleted. Silently dropping addresses would make the
        migration a data loss instead of a downgrade."""
        signup(fresh, "legacy.keeps")
        q("UPDATE accounts SET email = ? WHERE username = ?",
          ("keeps@example.com", "legacy.keeps"))
        assert fresh.get("/api/account/me").json()["account"]["emailPending"] is True
        assert fresh.post("/api/account/email/resend").json()["sent"] is True
        token = link_token(mailbox.last_to("keeps@example.com"))
        assert fresh.post("/api/account/email/verify", json={"token": token}).json()["hasEmail"]


# ------------------------------------------------------------ forgot password


class TestForgotIsBlind:
    """Every branch returns the same status and the same body. `/login` goes to
    real trouble to avoid leaking whether a username exists — a helpful
    "no account by that name" here would hand it over for free."""

    def answers(self, c):
        r = c.post("/api/account/forgot", json={"username": self.username})
        return r.status_code, r.json()

    def test_a_confirmed_account_and_a_name_nobody_has_read_the_same(self, fresh):
        token = enrol(fresh, "forgot.real", "forgotreal@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})

        real = fresh.post("/api/account/forgot", json={"username": "forgot.real"})
        absent = fresh.post("/api/account/forgot", json={"username": "nobody.at.all"})
        assert real.status_code == absent.status_code == 200
        assert real.json() == absent.json()

    def test_an_account_with_no_address_reads_the_same(self, fresh):
        signup(fresh, "forgot.noaddr")
        r = fresh.post("/api/account/forgot", json={"username": "forgot.noaddr"})
        absent = fresh.post("/api/account/forgot", json={"username": "nobody.either"})
        assert r.json() == absent.json()

    def test_an_unconfirmed_address_reads_the_same_and_is_not_written_to(self, fresh):
        """An address nobody proved they own must not receive a reset link —
        that would be the takeover the confirmation exists to prevent."""
        enrol(fresh, "forgot.unconfirmed", "forgotunconfirmed@example.com")
        mailbox.clear()
        r = fresh.post("/api/account/forgot", json={"username": "forgot.unconfirmed"})
        assert r.status_code == 200
        assert mailbox.last_to("forgotunconfirmed@example.com") is None
        assert not q("SELECT 1 FROM password_resets pr JOIN accounts a ON a.id = pr.account_id "
                     "WHERE a.username = ?", ("forgot.unconfirmed",)).fetchone()

    def test_a_confirmed_account_does_get_a_link(self, fresh):
        """The other half — a blind endpoint that also does nothing would pass
        every test above."""
        token = enrol(fresh, "forgot.works", "forgotworks@example.com")
        fresh.post("/api/account/email/verify", json={"token": token})
        mailbox.clear()
        fresh.post("/api/account/forgot", json={"username": "forgot.works"})
        message = mailbox.last_to("forgotworks@example.com")
        assert message is not None
        assert "#" in next(l for l in message.body.splitlines() if l.startswith("http"))

    def test_an_unknown_name_is_logged_even_though_the_answer_is_blind(self, fresh):
        """A run of these is the same enumeration signal `/login` records, and
        the response is deliberately blind to it — so the log is where the
        difference has to live."""
        fresh.post("/api/account/forgot", json={"username": "ghost.account"})
        rows = q("SELECT subject, detail FROM security_log WHERE kind = 'auth.unknown' "
                 "ORDER BY id DESC LIMIT 5").fetchall()
        assert any(r["subject"] == "ghost.account" and r["detail"] == "forgot-password"
                   for r in rows)

    def test_an_email_shaped_username_is_not_written_to_the_log(self, fresh):
        """Someone using their address as a username would otherwise have it
        recorded on every typo — the same care `/login` already takes."""
        fresh.post("/api/account/forgot", json={"username": "someone@example.com"})
        rows = q("SELECT subject FROM security_log WHERE kind = 'auth.unknown' "
                 "ORDER BY id DESC LIMIT 5").fetchall()
        assert any(r["subject"] == "<email-shaped>" for r in rows)
        assert not any("someone@example.com" == r["subject"] for r in rows)


class TestResetting:
    def prepared(self, c, username):
        address = f"{username.replace('.', '')}@example.com"
        token = enrol(c, username, address)
        c.post("/api/account/email/verify", json={"token": token})
        mailbox.clear()
        c.post("/api/account/forgot", json={"username": username})
        return link_token(mailbox.last_to(address))

    def test_the_new_password_is_the_one_that_works(self, fresh):
        token = self.prepared(fresh, "reset.works")
        assert fresh.post("/api/account/reset",
                          json={"token": token, "password": "a whole new one"}).status_code == 200
        fresh.cookies.clear()
        assert fresh.post("/api/account/login",
                          json={"username": "reset.works", "password": PASSWORD}).status_code == 401
        assert fresh.post("/api/account/login",
                          json={"username": "reset.works",
                                "password": "a whole new one"}).status_code == 200

    def test_it_signs_the_caller_in(self, fresh):
        """They have just proved control of the recovery address and chosen a
        password; making them type it again immediately proves nothing."""
        token = self.prepared(fresh, "reset.signsin")
        fresh.cookies.clear()
        r = fresh.post("/api/account/reset", json={"token": token, "password": "a whole new one"})
        assert r.json()["account"]["username"] == "reset.signsin"
        assert fresh.get("/api/account/me").json()["account"] is not None

    def test_every_other_session_ends(self, fresh):
        """The reason somebody is here is usually that somebody else might be
        signed in."""
        token = self.prepared(fresh, "reset.evicts")
        other = TestClient(fresh.app, base_url="https://testserver")
        other.post("/api/account/login", json={"username": "reset.evicts", "password": PASSWORD})
        assert other.get("/api/account/me").json()["account"] is not None

        fresh.post("/api/account/reset", json={"token": token, "password": "a whole new one"})
        assert other.get("/api/account/me").json()["account"] is None

    def test_it_works_exactly_once(self, fresh):
        token = self.prepared(fresh, "reset.once")
        assert fresh.post("/api/account/reset",
                          json={"token": token, "password": "a whole new one"}).status_code == 200
        assert fresh.post("/api/account/reset",
                          json={"token": token, "password": "another new one"}).status_code == 400

    def test_it_expires(self, fresh):
        token = self.prepared(fresh, "reset.expires")
        q("UPDATE password_resets SET expires_at = ? WHERE token_hash = ?",
          (int(time.time()) - 1, _token_hash(token)))
        assert fresh.post("/api/account/reset",
                          json={"token": token, "password": "a whole new one"}).status_code == 400

    def test_the_window_is_an_hour(self, fresh):
        """Shorter than a confirmation link, because this one *is* a password."""
        token = self.prepared(fresh, "reset.ttl")
        row = q("SELECT created_at, expires_at FROM password_resets WHERE token_hash = ?",
                (_token_hash(token),)).fetchone()
        assert row["expires_at"] - row["created_at"] == pytest.approx(RESET_TTL, abs=2)

    def test_the_token_is_stored_only_as_a_hash(self, fresh):
        token = self.prepared(fresh, "reset.hashed")
        rows = q("SELECT token_hash FROM password_resets").fetchall()
        assert all(r["token_hash"] != token for r in rows)
        assert any(r["token_hash"] == _token_hash(token) for r in rows)

    def test_asking_twice_retires_the_first_link(self, fresh):
        first = self.prepared(fresh, "reset.retired")
        fresh.post("/api/account/forgot", json={"username": "reset.retired"})
        assert fresh.post("/api/account/reset",
                          json={"token": first, "password": "a whole new one"}).status_code == 400

    def test_a_reset_token_cannot_confirm_an_address(self, fresh):
        token = self.prepared(fresh, "reset.crossuse")
        assert fresh.post("/api/account/email/verify",
                          json={"token": token}).status_code == 400

    def test_a_short_password_is_refused_before_the_token_is_spent(self, fresh):
        """Otherwise a fat-fingered password burns the one link they have."""
        token = self.prepared(fresh, "reset.short")
        assert fresh.post("/api/account/reset",
                          json={"token": token, "password": "short"}).status_code == 422
        assert fresh.post("/api/account/reset",
                          json={"token": token, "password": "a whole new one"}).status_code == 200

    def test_a_made_up_token_is_refused(self, fresh):
        assert fresh.post("/api/account/reset",
                          json={"token": "x" * 40,
                                "password": "a whole new one"}).status_code == 400
