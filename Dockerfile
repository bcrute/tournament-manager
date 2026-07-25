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
