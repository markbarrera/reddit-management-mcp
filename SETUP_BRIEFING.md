# Setup Briefing: Onramp Funds Reddit Intelligence MCP

**Instructions to Claude (read first):**

You are helping me deploy a Reddit Intelligence MCP server to Railway and connect it to Claude Desktop. The code is already written and pushed to a GitHub repo I own. I just need you to guide me through the deployment clicks.

**How to behave:**
- Walk me through **one step at a time**. Wait for my confirmation ("done", "ok", or output) before moving to the next step.
- If I hit an error, help me debug before continuing.
- Don't dump the whole guide at once. Stay interactive.
- Don't make up steps — the procedure below is exact. If I ask something not covered, say so and offer to think it through.
- Be concise. I want to ship this in 20 minutes.

---

## Context: what I'm deploying

A Reddit market-intelligence and content-strategy MCP server for **Onramp Funds**, a revenue-based financing company for ecommerce sellers. The repo contains:

- `server_remote.py` — FastMCP HTTP server with Bearer-token auth (Railway entry point)
- `reddit_scraper.py` — Reddit scraper (OAuth API or public JSON fallback)
- `classifier.py` — Claude-powered classifier grounded in brand docs
- `db.py` — SQLite schema (threads, classifications, grounding docs)
- `slack_digest.py` — daily Slack digest of high-priority threads
- `grounding_docs/` — six Markdown files (competitive positioning, voice & tone, Reddit engagement rules, product messaging, ICP personas, GEO content strategy) that auto-load into the database on startup
- `Dockerfile` + `railway.json` — deploy config

The repo is at: **`<FILL IN GITHUB URL>`** (I'll paste the URL when we start).

---

## Pre-flight: confirm I have these tabs/tools open

Before we start, confirm I have:
- [ ] Browser logged into GitHub (Railway will need this)
- [ ] Browser ready to log into Railway (railway.com)
- [ ] Browser ready to log into Anthropic (console.anthropic.com)
- [ ] Browser ready to log into Reddit (reddit.com)
- [ ] A terminal with `openssl` (any Mac/Linux works; Windows can use git-bash or PowerShell)
- [ ] A scratch text file open for stashing credentials as we generate them

---

## Step 1 — Generate the MCP API key (30 sec)

Have me run this in my terminal:

```bash
echo "sk-onramp-$(openssl rand -hex 24)"
```

It should print something like `sk-onramp-a1b2c3...` (a 48-character hex string after the prefix).

**Ask me to paste the output.** Save it as `MCP_API_KEY` in my scratch file. We'll use it twice: once in Railway env vars, once in Claude Desktop config.

---

## Step 2 — Anthropic API key (2 min)

Send me to: https://console.anthropic.com/settings/keys

Tell me to:
1. Click "Create Key"
2. Name it `onramp-reddit-mcp`
3. Copy the key (starts with `sk-ant-`)
4. Also tell me to go to Plans & Billing and set a monthly spend limit of $50

**Ask me to paste the `sk-ant-...` key.** Save it as `ANTHROPIC_KEY` in my scratch file.

---

## Step 3 — Reddit "script" app (3 min)

Send me to: https://www.reddit.com/prefs/apps

Tell me:
1. Log into Reddit with the account that will be associated with Onramp's Reddit presence (ideally a real-name employee account — see the persona section below if I need help with this)
2. Scroll to the very bottom of the page
3. Click "are you a developer? create an app..."
4. Fill in:
   - **name:** `onramp-reddit-mcp`
   - **type:** select the **script** radio button
   - **redirect uri:** `http://localhost:8080`
5. Click "create app"

**Ask me to paste four values from the resulting page:**
- The **client ID** — random string just under "personal use script"
- The **secret** — the long string labeled "secret"
- The **username** I'm logged in as
- The **password** for that account

Save these as `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`.

---

## Step 4 — Deploy on Railway (3 min)

Send me to: https://railway.com/new

Tell me:
1. Click "Deploy from GitHub repo"
2. If Railway isn't connected to my GitHub, authorize it
3. Select my repo (the GitHub URL I shared at the top)
4. Railway auto-detects `railway.json` and `Dockerfile`. Click Deploy.
5. Wait ~2 minutes for the first build

**Expected outcome:** the first build will succeed, but the app will crash on startup because env vars aren't set yet. That's fine — that's Step 5.

**Ask me to confirm the build completed** (Railway will show a green checkmark, then the crash will show as red).

---

## Step 5 — Environment variables (2 min)

In the Railway project, tell me:
1. Click on the service (the box with my repo's name)
2. Click the **Variables** tab
3. Click **Raw Editor**
4. Paste this template:

```
ANTHROPIC_API_KEY=<paste ANTHROPIC_KEY>
REDDIT_MCP_API_KEYS=onramp:<paste MCP_API_KEY>
REDDIT_CLIENT_ID=<paste REDDIT_CLIENT_ID>
REDDIT_CLIENT_SECRET=<paste REDDIT_CLIENT_SECRET>
REDDIT_USERNAME=<paste REDDIT_USERNAME>
REDDIT_PASSWORD=<paste REDDIT_PASSWORD>
REDDIT_DB_PATH=/data/reddit.db
```

**Important formatting notes:**
- `REDDIT_MCP_API_KEYS` uses the format `<name>:<key>` — keep the `onramp:` prefix
- No quotes around values
- One per line

5. Click "Update Variables". Railway will redeploy automatically.

**Ask me to confirm the redeploy succeeded.** This time it should stay running.

---

## Step 6 — Persistent volume (1 min)

Without this, my database gets wiped every time Railway redeploys.

Tell me:
1. Service → **Settings** tab
2. Scroll down to **Volumes**
3. Click **+ New Volume**
4. **Mount path:** `/data`
5. Save. Railway redeploys once more (this is fine).

**Ask me to confirm the volume appears as mounted.**

---

## Step 7 — Generate public URL (30 sec)

Tell me:
1. Service → **Settings** → scroll to **Networking**
2. Click **Generate Domain**
3. Copy the URL Railway gives me (e.g. `something-production.up.railway.app`)

**Ask me to paste the URL.** Save it as `RAILWAY_URL` in my scratch file.

---

## Step 8 — Smoke test (1 min)

Tell me to open in my browser:

```
https://<RAILWAY_URL>/health
```

**Expected response:**
```json
{"status": "healthy", "service": "onramp-funds-reddit-intelligence",
 "threads_in_db": 0, "classified": 0}
```

**Ask me to paste what I see.**

If it doesn't look like that:
- **"This site can't be reached"** → Railway is still deploying. Wait 60 seconds and refresh.
- **502 / 503** → app crashed. Send me to Railway → Deployments → click latest → View Logs. Ask me to paste the last 30 lines of logs and help me debug. Common causes:
  - Missing env var (most often a typo in a name)
  - `ANTHROPIC_API_KEY` invalid
  - Volume not mounted (logs will say "Database initialized at reddit_intelligence.db" instead of `/data/reddit.db`)
- **401/403** → that's actually a good sign; means the auth middleware is working. /health shouldn't require auth though, so flag this for debugging.

---

## Step 9 — Connect Claude Desktop (3 min)

Have me locate this file:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

If the file doesn't exist yet, I create it.

Tell me to put this in it (replacing any existing content carefully — if there's already an `mcpServers` object, add the `onramp-reddit` key alongside existing servers):

```json
{
  "mcpServers": {
    "onramp-reddit": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://<RAILWAY_URL>/mcp",
        "--header",
        "Authorization:Bearer <MCP_API_KEY>"
      ]
    }
  }
}
```

Have me substitute `<RAILWAY_URL>` and `<MCP_API_KEY>` with the real values from my scratch file.

Then:
1. **Fully quit** Claude Desktop (not just close the window — File menu → Quit, or Cmd+Q on Mac)
2. Relaunch Claude Desktop
3. Open a new chat
4. Look for the tools icon in the input bar — should show 10 `reddit_*` tools

**Have me run this prompt to verify everything is wired up:**

> List the grounding docs available in the Onramp Reddit MCP.

Expected response: Claude calls `reddit_list_grounding_docs` and returns six docs (competitive_positioning, voice_tone, reddit_engagement_rules, product_messaging, icp_personas, geo_content_strategy) with file sizes.

**If the tools don't show up:**
- Did I fully quit Claude Desktop? (Cmd+Q, not just close window)
- Is `npx` installed? Run `which npx` in terminal. If missing, install Node.js from nodejs.org.
- JSON syntax error in config? Run `cat <path-to-config> | python -m json.tool` to validate.

**If the tools show up but the prompt fails:**
- Check the error message — it'll say if it's auth (wrong API key) or network (wrong URL) or server-side
- Have me re-check the Railway URL has the `/mcp` suffix

---

## Step 10 — Real end-to-end test (3 min)

Once the grounding docs test works, have me run:

> Use the Onramp Reddit MCP to ingest 10 threads from r/AmazonSeller. Skip comment-fetching to keep it fast.

Expected: Claude calls `reddit_ingest` with `subreddits=["AmazonSeller"], limit=10, fetch_comments=False`. Returns a summary with 10 threads and their titles.

Then:

> Now classify those threads.

Expected: Claude calls `reddit_classify`. Returns priority assignments for each.

Then:

> Show me the highest-priority thread and generate a full participation guide for it.

Expected: Claude returns a draft response in Onramp's Reddit voice, with disclosure, narrative check, competitor protocol.

**If any of these fail**, look at the error and help me debug.

🎉 **Once all three work, the core deployment is done.**

---

## Optional: Step 11 — Slack daily digest (5 min)

This is the morning briefing that posts urgent threads to a Slack channel automatically. Skip if I want to ship the core first and add this later.

If I want to do it now:

**11a. Create the Slack webhook**

Send me to: https://api.slack.com/apps

Tell me:
1. Click **Create New App** → **From scratch**
2. Name: `Onramp Reddit Digest`
3. Pick the workspace
4. Left sidebar → **Incoming Webhooks** → toggle **Activate** on
5. Click **Add New Webhook to Workspace**
6. Pick the target channel (e.g. `#reddit-intelligence` or `#growth`)
7. Authorize
8. Copy the webhook URL — looks like `https://hooks.slack.com/services/T.../B.../...`

**Ask me to paste the webhook URL.** Save as `SLACK_WEBHOOK_URL`.

**11b. Add the webhook to Railway**

In Railway → Variables tab → add one more line:

```
SLACK_WEBHOOK_URL=<paste SLACK_WEBHOOK_URL>
```

Click Update. Railway redeploys.

**11c. Set up the cron job**

In Railway project → click **+ New** (top-right) → **Cron Job**

- **Schedule:** `0 13 * * *` (this is 13:00 UTC = 8 AM Central, adjust for Onramp HQ's timezone if needed)
- **Command:** `python slack_digest.py`
- **Variables:** Click "Add Reference" to inherit all parent service variables. Then add one extra: `REDDIT_DIGEST_INGEST=1` (so it scrapes fresh threads each morning)

Save.

**11d. Test it manually**

In the cron service → click **Trigger Now**.

Within 60 seconds, check the Slack channel. Should see a digest post (will say "No new urgent or high-priority threads in the last 24 hours" if the database is still empty — that's fine; it confirms the wiring works).

---

## Reference: my env var scratch file

By the end I should have:

```
MCP_API_KEY        = sk-onramp-...
ANTHROPIC_KEY      = sk-ant-...
REDDIT_CLIENT_ID   = ...
REDDIT_CLIENT_SECRET = ...
REDDIT_USERNAME    = ...
REDDIT_PASSWORD    = ...
RAILWAY_URL        = ...-production.up.railway.app
SLACK_WEBHOOK_URL  = https://hooks.slack.com/services/...
```

I'll need `MCP_API_KEY` and `RAILWAY_URL` again to share with the Onramp team if I'm handing this off.

---

## Reference: what gets handed off to Onramp afterward

After this works, I'll send Onramp:
- The Railway URL
- The `MCP_API_KEY` (the `sk-onramp-...` one)
- The `ONRAMP_HANDOFF.md` file from the repo (which covers everything they need beyond what we did here, including the Reddit persona setup section)

I don't need to share the Anthropic key or the Reddit OAuth credentials — those are server-side only.

---

## Reference: if I want a different Reddit persona than "real-name employee"

The grounding docs assume Onramp will use a real-name employee account (e.g. Eric Youngstrom) on Reddit. If Onramp picks a different approach (branded team account, or a different person), the disclosure language in `grounding_docs/voice_tone.md` and `grounding_docs/reddit_engagement_rules.md` needs minor edits — search for "Eric" and "founder" and adjust. See §8 of ONRAMP_HANDOFF.md for the full rationale.

This doesn't block deployment — I can ship the system today and edit the docs once Onramp confirms the persona.

---

**Start now by asking me to confirm I have the pre-flight tabs/tools open and to paste my GitHub repo URL. Then walk me through Step 1.**
