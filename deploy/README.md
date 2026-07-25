# Reverse proxy: who owns what

The VPS runs one Caddy in front of every app on the host — currently
`mtg.skadoosh.dev` (this repo) and `social.skadoosh.dev` (an independent app).
A single shared Caddyfile meant either app's deploy could clobber the other's
routing, so the config is split:

- `/opt/caddy/Caddyfile` — root config: global options plus
  `import sites/*.caddy`. Shared ground, changes rarely, applied by hand.
  Reference copy: [`caddy/Caddyfile`](caddy/Caddyfile).
- `/opt/caddy/sites/mtg.caddy` — this app's vhost, shipped automatically by
  the deploy workflow. Source of truth: [`caddy/sites/mtg.caddy`](caddy/sites/mtg.caddy).
- `/opt/caddy/sites/social.caddy` — the social app's vhost. Not ours; nothing
  in this repo reads, writes, or ships it.

The deploy workflow ships only `sites/mtg.caddy`, then runs
`caddy validate` against the **merged** config (so a typo here that would break
social's config fails the deploy instead of the site), then a graceful
`caddy reload`. On validation failure the previous vhost is restored and the
running Caddy is untouched; on reload failure Caddy keeps serving the old
config. (If the VPS were ever rebuilt on the old single-file layout, the
workflow detects the missing `sites/` directory and skips the vhost step with
a warning, so app deploys keep working either way.)

## How the VPS got this layout (migration done 2026-07-24)

The single shared `/opt/caddy/Caddyfile` was split in place; kept here as the
record and the recipe if the host is ever rebuilt:

1. Backed up `Caddyfile` and `docker-compose.yml` (`*.pre-split.20260724`),
   made `sites/`, moved social's site block **verbatim** to
   `sites/social.caddy`, copied this repo's `caddy/sites/mtg.caddy` and root
   `caddy/Caddyfile` (global options + `import sites/*.caddy`) into place.
2. Changed the caddy container's mount from `./Caddyfile:/etc/caddy/Caddyfile:ro`
   to `.:/etc/caddy:ro` — the **directory**, not the file. A single-file bind
   mount pins the file's inode, so the `scp` in the deploy would silently
   update the host file while the container keeps reading the old content —
   the directory mount is load-bearing, not a style choice.
3. Validated the merged config before touching the running container:

   ```sh
   docker run --rm -v /opt/caddy:/etc/caddy:ro caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
   ```

4. `docker compose up -d --force-recreate caddy` (a few seconds' blip — the
   one moment both sites drop), then confirmed both domains answer 200 and
   `docker exec caddy caddy validate`/`caddy reload` work in the new container.
5. Ran `caddy fmt --overwrite` on all three files so reloads log no
   formatting warning, and deleted a stale `Caddyfile.new` (an mtg-only copy
   from 2026-07-23, pre-social — applying it would have dropped social from
   the proxy; its content lives in this repo).

Ongoing: edits to `caddy/sites/mtg.caddy` ship on the next push to `main`;
edits to the root Caddyfile remain manual (`caddy validate`, then
`docker exec caddy caddy reload --config /etc/caddy/Caddyfile`).

## Other shared-host boundaries

The rest of the deploy is already scoped to this app: it writes only
`/opt/apps/mtg`, restarts only the `mtg` compose service, and prunes only
images labeled `app=mtg` (the label is set in the Dockerfile — a bare
`docker image prune` here would collect other apps' dangling images too).
