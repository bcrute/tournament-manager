"""Why this app may show Magic card content, and what keeps that true.

Scryfall serves card data under the Wizards Fan Content Policy, and that policy
is **noncommercial**. This repo has been on both sides of that:

- **July 2026** — a Scryfall integration was removed specifically to drop the
  licence chain, at a point when a paid tier here was still an open question.
  A regression test asserted the proxy stayed gone.
- **August 2026** — the question closed the other way. This app is
  noncommercial permanently; the commercial vehicle is a separate events/social
  project that ships no Magic content at all. That is what makes it safe for
  Scryfall to come back, and `/rulings` uses it.

The sequence in between is why this file exists. That regression test was
deleted during an unrelated refactor, so when the integration was reintroduced
nothing was left to notice — and nobody re-read the licensing analysis, because
nothing pointed at it. A decision with nothing enforcing it is a decision that
quietly stops being true.

This is the repo-shape half of the guard. The attribution wording and the
frontend dependency check are in `frontend/src/fanContent.test.ts`, which is
where those files live.
"""

from conftest import deployment_file, repo_file

#: Payment processors and billing SDKs. One of these appearing in this app is
#: the event that invalidates the licence position — not a routine dependency
#: bump. See `docs/commercial-position.md` §3.
PAYMENT_SDKS = (
    "stripe",
    "paddle",
    "lemonsqueezy",
    "paypal",
    "braintree",
    "chargebee",
    "recurly",
    "squareup",
)

WHY_IT_MATTERS = (
    "This app is noncommercial, and that is what permits its use of Scryfall "
    "and Magic card content under the Wizards Fan Content Policy. Read "
    "docs/commercial-position.md before going further — the commercial product "
    "is a separate project and ships no Magic content at all."
)


class TestTheDecisionIsStillWrittenDown:
    """A test that asserts a document says something is unusual, and earned
    here: this guard's entire justification lives in that document. Delete the
    reasoning and the rule becomes folklore."""

    def position(self) -> str:
        return deployment_file("docs/commercial-position.md").read_text(encoding="utf-8")

    def test_it_says_this_app_is_noncommercial_permanently(self):
        text = self.position().lower()
        assert "noncommercial" in text
        assert "permanently" in text, (
            "the word that distinguishes a settled decision from 'for now' — "
            + WHY_IT_MATTERS
        )

    def test_it_names_the_policy_this_rests_on(self):
        assert "Fan Content Policy is noncommercial" in self.position()

    def test_it_points_at_the_separate_commercial_project(self):
        text = self.position().lower()
        assert "separate events/social project" in text, (
            "where the commercial work goes instead, so the split is findable"
        )


class TestNothingHereChargesAnyone:
    """Checked the only way a test can — the absence of a payment integration.

    A proxy rather than a proof: money could change hands without an SDK in the
    repo. It catches the realistic case, which is somebody wiring up a
    processor without connecting it to a licensing question three documents
    away, and the failure message is the connection.
    """

    def test_no_payment_dependency(self):
        for name in ("requirements.txt", "requirements-dev.txt"):
            path = repo_file(f"backend/{name}", name)
            text = path.read_text(encoding="utf-8").lower()
            found = [sdk for sdk in PAYMENT_SDKS if sdk in text]
            assert not found, f"{name} pulls in {found}. {WHY_IT_MATTERS}"

    def test_no_payment_code_in_the_application(self):
        app_dir = repo_file("backend/app", "app")
        offenders = []
        for path in app_dir.glob("*.py"):
            lowered = path.read_text(encoding="utf-8").lower()
            offenders += [f"{path.name}:{sdk}" for sdk in PAYMENT_SDKS if sdk in lowered]
        assert not offenders, f"{offenders}. {WHY_IT_MATTERS}"
