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
RUN python -m pytest tests -q --cov=app --cov-report=term --cov-fail-under=90 && touch /tests-passed

# Browser tests against the real artifact: the built frontend served by the
# actual app. The Playwright image ships the browsers, so CI doesn't download
# ~120MB per build. Runs as a build stage, so a failure fails the image.
FROM mcr.microsoft.com/playwright:v1.61.1-noble AS e2e
WORKDIR /e2e
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./backend/requirements.txt
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app ./backend/app
COPY data ./data
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend/playwright.config.ts ./frontend/
COPY frontend/e2e ./frontend/e2e
COPY --from=frontend /fe/dist ./frontend/dist
ENV CI=true PATH="/venv/bin:$PATH"
RUN cd frontend && npx playwright test && touch /e2e-passed

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY data ./data
COPY --from=backend-test /tests-passed /tmp/tests-passed
COPY --from=e2e /e2e-passed /tmp/e2e-passed
COPY --from=frontend /fe/dist ./static
# run unprivileged; /appdata is a mounted volume owned by the same uid on the host
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
