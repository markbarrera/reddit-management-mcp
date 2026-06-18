# Deployment & Persistence (Railway)

Production runs on Railway from the `main` branch, built from the `Dockerfile`,
started with `python server_remote.py`. Public URL:
`https://reddit-mcp-production-59c2.up.railway.app` (MCP endpoint `/mcp`).

## Data persistence — IMPORTANT

The database is **SQLite** (`db.py`), stored at the path in the
`REDDIT_DB_PATH` env var (default: `reddit_intelligence.db`, a **relative path
inside the container**).

Railway containers have an **ephemeral filesystem**. With no volume mounted,
the SQLite file lives on that ephemeral disk, so **every redeploy or container
restart wipes all scraped/classified threads.** Only the grounding docs are
restored, because they are re-seeded from `grounding_docs/` on boot
(`_seed_grounding_docs()`); scraped Reddit threads are not in the repo and are
lost. This is a silent data-loss bug independent of any outage.

### Fix: mount a persistent Railway volume

1. **Railway dashboard → the `reddit-mcp` service → Variables**, add:

   ```
   REDDIT_DB_PATH=/data/reddit_intelligence.db
   ```

2. **Service → Settings → Volumes → + New Volume.**
   - Mount path: `/data`
   - Attach it to the `reddit-mcp` service.

3. **Redeploy.** On boot, `db.py` creates the parent directory if needed and
   `init_db()` initializes the schema on the volume. The DB now survives
   redeploys and restarts.

> ⚠️ **One-time data loss on cutover:** the redeploy that introduces the volume
> starts from an **empty** `/data`, because the current ~965 threads live only
> on the old ephemeral disk and there is no export endpoint. After the volume is
> live, **re-run ingestion** (e.g. ingest the default subreddits/keywords and
> re-classify) to repopulate. Everything ingested *after* the volume is mounted
> persists. If preserving the current rows is critical, copy the existing DB
> file onto the volume via a one-off `railway run`/`railway ssh` session *before*
> the cutover redeploy.

### Verifying persistence

After the volume is mounted and you've ingested some threads:

```bash
curl -s https://reddit-mcp-production-59c2.up.railway.app/health
# note threads_in_db
```

Trigger a redeploy, then curl `/health` again — `threads_in_db` should be
unchanged (previously it would have dropped back to 0).

## Resilience settings (already in `railway.json`)

- `healthcheckPath: /health` — the DB read here is wrapped in try/except, so a
  transient SQLite hiccup returns `200` `"degraded"` instead of failing the
  health check and triggering a restart loop.
- `restartPolicyMaxRetries: 10` — a transient boot flap cannot exhaust the
  retry cap and leave the service with no running container (which surfaces to
  MCP clients as "MCP server connection lost").

## Future: real Postgres / Neon

If you want the "Neon Postgres" model to actually be true (shared, durable,
no single-writer limits), `db.py` would need to move from `sqlite3` to a
Postgres driver (`psycopg`), parameterized via a `DATABASE_URL`, with the
`?`-style placeholders converted to `%s` and `executescript` split into
individual statements. That is a larger change than the volume fix above and
is tracked separately.
