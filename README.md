# mtg

Magic: The Gathering apps, served at https://mtg.skadoosh.dev.

## Stack

- **Backend**: FastAPI (Python 3.12), serves the API under `/api` and the built frontend as static files.
- **Frontend**: Vite + React + TypeScript.
- **Deploy**: push to `main` → GitHub Actions builds the Docker image, ships it to the VPS over SSH (`docker save | docker load`), restarts the compose stack, and ships this app's Caddy vhost (`deploy/caddy/sites/mtg.caddy`, validated then gracefully reloaded). Caddy on the VPS terminates TLS for every app on the host; each app owns only its own `sites/*.caddy` file, so a deploy here cannot touch `social.skadoosh.dev`'s routing (`deploy/README.md`).

## Local development

```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload   # needs a static/ dir or comment out the mount

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

## Production build

```bash
docker build -t mtg:latest .
docker run --rm -p 8000:8000 mtg:latest
```
