FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run test && npm run build

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
# This stage is thrown away; the final image copies /tests-passed and nothing
# else out of it.
COPY docker-compose.yml ./docker-compose.yml
COPY deploy ./deploy
RUN python -m pytest tests -q --cov=app --cov-report=term --cov-fail-under=90 && touch /tests-passed

FROM python:3.12-slim
# Scopes the deploy's `docker image prune --filter label=app=mtg`: the VPS
# hosts other apps' images, which are not ours to collect.
LABEL app=mtg
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY data ./data
COPY --from=backend-test /tests-passed /tmp/tests-passed
COPY --from=frontend /fe/dist ./static
# run unprivileged; /appdata is a mounted volume owned by the same uid on the host
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
