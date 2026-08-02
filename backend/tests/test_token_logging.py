"""Entrant tokens must never reach an access log (contract §1).

The token is a query parameter, so every request target carries a live
credential. Two things write those targets down — uvicorn's own access log and
Caddy's — and each has to redact for itself. These tests pin the app half end
to end (a record shaped exactly like uvicorn's, through uvicorn's own
formatter) and assert the proxy half is declared in the vhost this repo ships.
"""

import io
import logging
from pathlib import Path

import pytest
from uvicorn.logging import AccessFormatter

from app.access_log import RedactingFilter, install, redact
from conftest import deployment_file

TOKEN = "s3cret-entrant-token-abc123"


class TestRedact:
    def test_entrant_token_value_is_replaced(self):
        out = redact(f"/api/tournament/ABCDE?token={TOKEN}")
        assert TOKEN not in out
        assert out == "/api/tournament/ABCDE?token=REDACTED"

    def test_path_and_parameter_name_survive(self):
        # what was called, and that it was called with a token, stays readable
        out = redact(f"/api/tournament/ABCDE/pods/3/call?token={TOKEN}")
        assert out.startswith("/api/tournament/ABCDE/pods/3/call?token=")

    def test_other_parameters_are_untouched(self):
        out = redact(f"/x?seat=4&token={TOKEN}&view=pods")
        assert out == "/x?seat=4&token=REDACTED&view=pods"

    def test_token_not_first_parameter(self):
        assert redact(f"/x?a=1&token={TOKEN}") == "/x?a=1&token=REDACTED"

    def test_credential_like_names_are_covered(self):
        for name in ("token", "roomToken", "access_token", "api_key", "signature"):
            out = redact(f"/x?{name}={TOKEN}")
            assert TOKEN not in out, name
            assert f"{name}=REDACTED" in out, name

    def test_case_insensitive_name(self):
        assert redact(f"/x?TOKEN={TOKEN}") == "/x?TOKEN=REDACTED"

    def test_stops_at_fragment_and_whitespace(self):
        assert redact(f"/x?token={TOKEN}#frag") == "/x?token=REDACTED#frag"
        assert redact(f'"GET /x?token={TOKEN} HTTP/1.1"') == '"GET /x?token=REDACTED HTTP/1.1"'

    def test_empty_value_is_harmless(self):
        assert redact("/x?token=") == "/x?token=REDACTED"

    def test_nothing_to_redact_is_a_no_op(self):
        line = "/api/tournament/ABCDE/standings"
        assert redact(line) == line

    def test_a_path_segment_named_token_is_not_mangled(self):
        # only query parameters carry the credential; paths must stay legible
        assert redact("/api/token/refresh") == "/api/token/refresh"


class TestUvicornAccessLog:
    """The concrete leak: uvicorn's access log is on by default under the
    Dockerfile's bare `uvicorn app.main:app` and writes the full target."""

    @pytest.fixture
    def access_log(self):
        logger = logging.getLogger("test.uvicorn.access")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
        )
        logger.handlers = [handler]
        logger.filters = []
        logger.setLevel(logging.INFO)
        logger.propagate = False
        install(("test.uvicorn.access",))
        yield logger, stream
        logger.handlers = []
        logger.filters = []

    @staticmethod
    def _emit(logger, target):
        # exactly the call uvicorn's http protocol makes
        logger.info(
            '%s - "%s %s HTTP/%s" %d', "10.0.0.7:53124", "GET", target, "1.1", 200
        )

    def test_token_absent_from_formatted_line(self, access_log):
        logger, stream = access_log
        self._emit(logger, f"/api/tournament/ABCDE?token={TOKEN}")
        line = stream.getvalue()
        assert TOKEN not in line
        assert "/api/tournament/ABCDE?token=REDACTED" in line
        assert "200" in line

    def test_a_second_handler_added_later_also_sees_the_redacted_value(self, access_log):
        # the filter is on the logger, so it runs before any handler — including
        # one an operator (or uvicorn's dictConfig) attaches after us
        logger, _ = access_log
        extra = io.StringIO()
        logger.addHandler(logging.StreamHandler(extra))
        self._emit(logger, f"/api/tournament/ABCDE?token={TOKEN}")
        assert TOKEN not in extra.getvalue()

    def test_dict_config_does_not_drop_the_filter(self):
        # uvicorn configures logging around the app import; dictConfig replaces
        # handlers but not filters, which is what makes import-time install safe
        import logging.config

        name = "test.uvicorn.access.dictconfig"
        install((name,))
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "handlers": {"null": {"class": "logging.NullHandler"}},
                "loggers": {name: {"handlers": ["null"], "level": "INFO"}},
            }
        )
        assert any(isinstance(f, RedactingFilter) for f in logging.getLogger(name).filters)


class TestInstalledByTheApp:
    def test_importing_the_app_installs_the_filter(self):
        import app.main  # noqa: F401  - import is the thing under test

        for name in ("uvicorn.access", "uvicorn.error"):
            filters = logging.getLogger(name).filters
            assert any(isinstance(f, RedactingFilter) for f in filters), name

    def test_install_is_idempotent(self):
        name = "test.install.twice"
        install((name,))
        install((name,))
        logger = logging.getLogger(name)
        assert sum(isinstance(f, RedactingFilter) for f in logger.filters) == 1

    def test_dict_args_and_non_string_args_survive(self):
        # a record whose args are a dict, and one with no args at all
        record = logging.LogRecord(
            "x", logging.INFO, __file__, 1, "%(u)s", ({"u": f"/a?token={TOKEN}"},), None
        )
        RedactingFilter().filter(record)
        assert TOKEN not in record.getMessage()
        plain = logging.LogRecord("x", logging.INFO, __file__, 1, "no args here", None, None)
        RedactingFilter().filter(plain)
        assert plain.getMessage() == "no args here"


class TestProxyVhost:
    """The other half. Caddy cannot redact the app's log and the app cannot
    redact Caddy's, so the vhost this repo ships must declare its own filter."""

    @pytest.fixture(scope="class")
    def vhost(self):
        # This used to skip when `deploy/` was absent, which is what happened
        # in every CI build — the tree was outside the image's build context,
        # so the one place it mattered was the one place it never ran. The
        # Dockerfile copies it into the test stage now, and this asserts rather
        # than skips: if it goes missing again, that is a finding, not a
        # no-op.
        path = deployment_file("deploy/caddy/sites/mtg.caddy")
        assert path.is_file(), path
        return path.read_text()

    def test_access_log_redacts_the_token_query_parameter(self, vhost):
        assert "log {" in vhost
        assert "format filter" in vhost
        assert "request>uri query {" in vhost
        assert "replace token REDACTED" in vhost

    def test_still_only_ships_the_mtg_vhost(self, vhost):
        # deploy/README.md: this repo must never write another app's routing
        assert "social" not in vhost.split("mtg.skadoosh.dev {")[1]


class TestRoomIdentifiersToo:
    """A room's `url_id` is a credential now, so it gets the same treatment.

    Mostly it is not in a request target at all — the anonymous routes take it
    in a POST body, and invitations put it in a fragment the browser never
    sends. The exception is the legacy `?join=` link, which the client still
    reads, and which does reach a log line.
    """

    def test_a_legacy_join_link_does_not_land_in_the_log(self):
        line = '"GET /table?join=kJ3xR_9pQz-A1BcDeFgHi HTTP/1.1" 200'
        out = redact(line)
        assert "kJ3xR_9pQz-A1BcDeFgHi" not in out
        assert "join=REDACTED" in out
        assert "/table" in out, "the path is what makes the line worth keeping"

    def test_a_room_id_parameter_by_any_name(self):
        for name in ("roomId", "room_id", "roomUrlId"):
            out = redact(f"/api/table/rooms/seats?{name}=kJ3xR_9pQz-A1BcDeFgHi")
            assert "kJ3xR_9pQz-A1BcDeFgHi" not in out, name

    def test_the_five_character_code_is_still_logged(self):
        """It is a label, not a credential — redacting it would cost the one
        thing that makes a room's log lines traceable to a room."""
        line = '"GET /api/table/rooms/7Q4KP/me HTTP/1.1" 200'
        assert redact(line) == line
