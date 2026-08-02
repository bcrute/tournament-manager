"""Keep credentials out of access logs.

§1 of the API contract puts the entrant token in the query string, because the
player client re-fetches state with a cheap retryable `GET`. The cost of that
choice is that every request *target* carries a live credential, and a request
target is the one thing every access log writes down. A log line is a durable,
widely-copied artifact (container logs, `docker logs`, a paste in an issue), so
a token in it outlives the tournament it belongs to.

Uvicorn's access log is on by default and writes the full target, query string
included, so this is not hypothetical: without the filter below the app itself
is the leak. The proxy redacts the same parameter in its own log
(`deploy/caddy/sites/mtg.caddy`); both layers matter because both write logs,
and neither can redact the other's.

A room's `url_id` is the second credential this has to catch, and it is a
narrower job: since 2026-07-31 the anonymous room routes take it in a POST body
and invitation links carry it in a fragment, so it is not in a request target
to begin with. What remains is the legacy `?join=` form, which the client still
parses for links already in the world — those do reach the request line, so
`join` and `room` are matched below.

The value is replaced rather than the whole query dropped: which endpoint was
called with *a* token is useful when reading logs, the token itself never is.
"""

import logging
import re

REDACTED = "REDACTED"

# Matches a query parameter whose *name* looks like a credential, capturing the
# name (with its leading separator) and its value. Names are matched by
# substring so `token`, `roomToken` and `access_token` are all covered without
# an enumeration that a later endpoint could quietly fall outside of.
#
# Deliberately run over the whole log string rather than a parsed URL: what
# reaches a filter may be a bare target, a full request line, or a message with
# a URL embedded in it. A value ends at the next `&` or `#`, or at whitespace or
# a quote — uvicorn wraps the request line in double quotes.
_SENSITIVE = re.compile(
    r"""(?ix)
    (                                   # 1: separator and parameter name
      [?&]
      [^?&=\s"']*
      (?: token | secret | passwd | password | api[-_]?key | signature
        | join | room )
      [^?&=\s"']*
      =
    )
    ( [^&\s"'#]* )                      # 2: the value to drop
    """
)


def redact(text: str) -> str:
    """Replace credential-looking query parameter values in `text`."""
    return _SENSITIVE.sub(lambda m: m.group(1) + REDACTED, text)


class RedactingFilter(logging.Filter):
    """Rewrites records in place so no handler can ever see the raw value.

    A filter rather than a formatter: formatters are per-handler and uvicorn's
    logging config (or an operator's) may add handlers we never see, while a
    filter on the logger runs once, before any of them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        args = record.args
        if isinstance(args, dict):
            record.args = {
                key: redact(value) if isinstance(value, str) else value
                for key, value in args.items()
            }
        elif isinstance(args, tuple):
            record.args = tuple(
                redact(value) if isinstance(value, str) else value for value in args
            )
        return True


# uvicorn.access is the one that writes request targets today; the others are
# cheap insurance for the day the process is fronted by something else or the
# app logs a URL of its own.
_TARGET_LOGGERS = ("uvicorn.access", "uvicorn.error", "gunicorn.access", "app")


def install(logger_names: tuple[str, ...] = _TARGET_LOGGERS) -> None:
    """Attach the filter once per logger. Safe to call repeatedly.

    Filters survive a later `logging.config.dictConfig` (it replaces handlers,
    not filters), so installing at import time holds even though uvicorn
    configures logging around the app import.
    """
    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
