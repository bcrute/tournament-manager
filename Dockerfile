# Two things live here, and the stage order is what keeps them apart.
#
#   --target runtime   the shipped image, and nothing else. What a deploy builds.
#   --target test      the suites. What `scripts/ci` and the PR check build.
#
# The runtime stage is deliberately defined **before** the test stages. The
# classic builder — still what some Docker installs use, including the one this
# was developed against — builds every stage up to `--target` in file order,
# regardless of what the target actually depends on. A test stage sitting above
# `runtime` would therefore be built during a deploy no matter how the
# dependencies are drawn. Ordering is the only portable way to say "never build
# these for a deploy".
#
# The trade is real and worth naming: the shipped image no longer carries proof
# its tests passed. It used to — the final stage copied a /tests-passed marker
# out of the test stage, which made building an untested image impossible. The
# gate is now a process rather than a mechanism: `scripts/ci` before pushing to
# main, and the PR check for anything that goes through one. See AGENTS.md.

# ---------------------------------------------------------------- build the UI

FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# `npm run build` is `tsc && vite build`, so a type error still fails a deploy.
# The unit tests moved to the frontend-test stage below.
RUN npm run build

# ------------------------------------------------------------ the image we ship

FROM python:3.12-slim AS runtime
# Scopes the deploy's `docker image prune --filter label=app=mtg`: the VPS
# hosts other apps' images, which are not ours to collect.
LABEL app=mtg
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY data ./data
COPY --from=frontend /fe/dist ./static
# run unprivileged; /appdata is a mounted volume owned by the same uid on the host
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ------------------------------------------------------------------ the suites
# Everything below this line is built only by `--target test`.

# Reuses the frontend stage's node_modules and sources rather than installing
# them a second time.
FROM frontend AS frontend-test
RUN npm run test && touch /tests-passed

FROM python:3.12-slim AS backend-test
WORKDIR /app
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY backend/app ./app
COPY backend/tests ./tests
COPY data ./data
# Deployment shape, read by the tests and by nothing else. `TestTheTrustBoundary`
# asserts that no host port is published and that Caddy trusts only private
# ranges — the two facts that make believing `X-Forwarded-For` safe — and
# `TestTheVhost` asserts the access log redacts entrant tokens. Without these
# here they skip, and a guard that skips in CI is a guard that isn't one.
COPY docker-compose.yml ./docker-compose.yml
COPY deploy ./deploy
# The licence position that permits this app to show Magic card content is
# recorded in docs/, and `test_licence_position.py` asserts it is still there.
# A test whose stated rationale has been deleted is a rule nobody can evaluate.
COPY docs ./docs
RUN python -m pytest tests -q --cov=app --cov-report=term --cov-fail-under=90 && touch /tests-passed

# The join point, so one `--target test` runs both suites. Nothing ships from
# here; it exists to give the two stages a single name to ask for.
FROM scratch AS test
COPY --from=frontend-test /tests-passed /frontend-tests-passed
COPY --from=backend-test /tests-passed /backend-tests-passed
