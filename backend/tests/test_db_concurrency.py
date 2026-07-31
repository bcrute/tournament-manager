"""One connection, many threads: a read must not lose a row that is there.

Every request in this app shares a single SQLite connection. `q()` used to
return the live cursor with `_db_lock` already released, so callers fetched
outside it — and another thread's `commit()` landing between `execute()` and
`fetchone()` reset the pending statement. `fetchone()` then returned `None`
for a row that existed, and raised nothing.

That is a silent wrong answer inside an authorization check: `get_player()`
turned it into **403 "not a player in this room"** for a player who was
sitting in it. It only appeared under concurrent load, which is why the e2e
suite failed a different test on every full run and none of them alone.

These tests drive the real `q()` from threads. On the old implementation the
first one fails within a second or two.
"""

import threading

import pytest

from app.db import q


@pytest.fixture
def scratch():
    q("CREATE TABLE IF NOT EXISTS race_probe (id INTEGER PRIMARY KEY, tag TEXT, token TEXT)")
    q("DELETE FROM race_probe")
    q("INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("seated", "the-real-token"))
    yield
    q("DROP TABLE IF EXISTS race_probe")


def _hammer(read_once, write_once, seconds=4.0, readers=4, writers=4):
    """Run readers and writers together; return whatever the readers noticed."""
    stop = threading.Event()
    problems: list[str] = []

    def reader():
        while not stop.is_set():
            try:
                if read_once() is None:
                    problems.append("a row that exists came back as None")
            except Exception as e:  # a raised error is still a failure, just a louder one
                problems.append(f"{type(e).__name__}: {e}")

    def writer():
        while not stop.is_set():
            try:
                write_once()
            except Exception as e:
                problems.append(f"writer {type(e).__name__}: {e}")

    threads = [threading.Thread(target=reader) for _ in range(readers)]
    threads += [threading.Thread(target=writer) for _ in range(writers)]
    for t in threads:
        t.start()
    stop.wait(seconds)
    stop.set()
    for t in threads:
        t.join()
    return problems


class TestConcurrentReads:
    def test_a_row_is_never_lost_while_another_thread_writes(self, scratch):
        """The exact shape of the 403: an authorization read racing a write."""
        problems = _hammer(
            read_once=lambda: q(
                "SELECT * FROM race_probe WHERE tag = ? AND token = ?",
                ("seated", "the-real-token"),
            ).fetchone(),
            write_once=lambda: q(
                "INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("noise", "x" * 200)
            ),
        )
        assert not problems, f"{len(problems)} bad reads, e.g. {problems[:3]}"

    def test_fetchall_keeps_every_row_under_load(self, scratch):
        """`fetchall()` had the same exposure — a truncated list is a roster
        with players missing from it, which is the same bug wearing a hat."""
        for i in range(20):
            q("INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("bulk", f"t{i}"))

        def read_once():
            rows = q("SELECT * FROM race_probe WHERE tag = ?", ("bulk",)).fetchall()
            # exactly the 20 just inserted; the writer only ever adds 'noise'
            return len(rows) if len(rows) == 20 else None

        problems = _hammer(
            read_once=read_once,
            write_once=lambda: q(
                "INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("noise", "y" * 200)
            ),
        )
        assert not problems, f"{len(problems)} short reads, e.g. {problems[:3]}"


class TestResultShape:
    """`q()` no longer returns a cursor, so pin what callers actually use."""

    def test_fetchone_walks_the_rows_then_returns_none(self, scratch):
        q("INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("seated", "second"))
        r = q("SELECT * FROM race_probe WHERE tag = ? ORDER BY id", ("seated",))
        assert r.fetchone()["token"] == "the-real-token"
        assert r.fetchone()["token"] == "second"
        assert r.fetchone() is None

    def test_fetchall_returns_what_is_left(self, scratch):
        q("INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("seated", "second"))
        r = q("SELECT * FROM race_probe WHERE tag = ? ORDER BY id", ("seated",))
        r.fetchone()
        assert [row["token"] for row in r.fetchall()] == ["second"]
        assert r.fetchall() == []

    def test_lastrowid_survives_the_write(self, scratch):
        cur = q("INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("new", "tok"))
        assert cur.lastrowid > 0
        got = q("SELECT tag FROM race_probe WHERE id = ?", (cur.lastrowid,)).fetchone()
        assert got["tag"] == "new"

    def test_a_write_is_committed_and_visible(self, scratch):
        q("INSERT INTO race_probe (tag, token) VALUES (?, ?)", ("committed", "tok"))
        assert q(
            "SELECT COUNT(*) AS n FROM race_probe WHERE tag = ?", ("committed",)
        ).fetchone()["n"] == 1

    def test_a_result_can_be_iterated(self, scratch):
        assert [r["tag"] for r in q("SELECT * FROM race_probe")] == ["seated"]
