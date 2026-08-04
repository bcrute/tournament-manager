# Contributing

This is a card tournament manager. It is free, noncommercial, and licensed
[Apache 2.0](LICENSE).

## Before you write anything

Read [`AGENTS.md`](AGENTS.md). It is written for coding agents but it is the
actual house style — the three surfaces, the boundaries that are pinned by
tests, and the rules about not claiming a control exists until you have
verified it. [`docs/security.md`](docs/security.md) holds the threat model and
the gaps that are knowingly carried.

Run the gate before you open anything:

```
scripts/ci          # what the PR check runs — the suites, in Docker
scripts/ci --e2e    # plus Playwright, which no workflow runs automatically
```

## Two things about scope

**Card games only.** MTG and Lorcana today; another card game is plausible.
Anything not played with a deck of cards belongs to a different project. See
[`docs/multi-game.md`](docs/multi-game.md).

**Noncommercial, permanently.** That is not a mood, it is what permits this app
to show Magic card content at all: Scryfall serves under the Wizards Fan
Content Policy and that policy is noncommercial. There are tests that fail if a
payment dependency appears. See
[`docs/commercial-position.md`](docs/commercial-position.md) before going
anywhere near that line.

## Sign your commits off (DCO)

Every commit needs a `Signed-off-by` line, which `git commit -s` adds:

```
Signed-off-by: Your Name <your.email@example.com>
```

That line is the [Developer Certificate of Origin](https://developercertificate.org/)
— a statement that you wrote the contribution, or otherwise have the right to
submit it under this project's licence.

It matters here for a specific reason rather than as ceremony. Parts of this
codebase — the account, mail, audit and rate-limiting work in particular — are
expected to be reused in a separate commercial project. Apache 2.0 §5 already
places inbound contributions under the same licence unless you say otherwise,
which permits that reuse; the DCO is the record that you had the right to
license them in the first place. Without it, a single contribution of uncertain
provenance is enough to make the whole file awkward to reuse, and untangling
that later is far more work than one flag on a commit.

If you would rather your contribution *not* be reusable that way, say so in the
pull request. Better to find out before it is merged than after.

## What gets a fast yes

- A regression test for a bug you hit. Several exist here precisely because a
  bug came back.
- Fixing something the docs claim but the code does not do. Those are the worst
  defects in this repo's history and finding one is a real contribution.
- Accessibility and mobile-layout fixes. The whole app is a phone held over a
  table.

## What needs a conversation first

- A new dependency. There are two runtime Python packages and four frontend
  ones, on purpose.
- Anything that touches a boundary listed in `AGENTS.md`, or that stores
  personal data. Playing this app requires no account and no personal data, and
  that is the central design decision rather than an accident of scope.
- Anything commercial, at all. See above.
