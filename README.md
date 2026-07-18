# mtg

Magic: The Gathering apps, served at https://mtg.skadoosh.dev.

## Stack

- **Backend**: FastAPI (Python 3.12), serves the API under `/api` and the built frontend as static files.
- **Frontend**: Vite + React + TypeScript.
- **Deploy**: push to `main` → Gitea Actions runner on unraid builds the Docker image, ships it to the VPS over SSH (`docker save | docker load`), and restarts the compose stack. Caddy on the VPS terminates TLS and routes `mtg.skadoosh.dev` to the container.

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
