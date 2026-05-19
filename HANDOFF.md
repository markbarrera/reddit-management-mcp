# Onramp Funds Reddit Intelligence MCP — Handoff

This is a Reddit market-intelligence and content-strategy MCP server scoped to Onramp Funds' brand, competitors, ICP, and GEO strategy. Once running, you connect it to Claude (Desktop, Code, or any MCP client) and ask it to scrape, classify, analyze, and draft Reddit content grounded in Onramp's positioning.

**What it gives you (10 tools):**
- `reddit_ingest` — scrape Onramp's target subreddits + keywords
- `reddit_ingest_urls` — bulk-ingest specific threads (e.g. from a peec.ai export); flags high-priority gaps where AI cites a thread but doesn't mention Onramp
- `reddit_search` — filter ingested threads by priority, competitor, score, time
- `reddit_classify` — Claude classifies each thread (topic, sentiment, competitors, personas, pain points, buyer language, participation priority) grounded in Onramp's brand docs
- `reddit_stats` — overview of what's in the database
- `reddit_participation_guide` — drafts a Reddit-voice reply for a specific thread, with narrative check + competitor protocol
- `reddit_thread_suggest` — generates thread-origination ideas (what_i_learned / honest_comparison / regulatory_explainer / myth_busting / resource / ama)
- `reddit_narrative_map` — competitive narrative analysis across the database
- `reddit_language_mine` — extracts buyer language patterns by persona
- `reddit_store_grounding_doc` / `reddit_get_grounding_doc` / `reddit_list_grounding_docs` — manage the six brand documents that ground every prompt

The six grounding docs (competitive positioning, voice & tone, Reddit engagement rules, product messaging, ICP personas, GEO content strategy) are checked into `grounding_docs/` as Markdown and **auto-seed into the database on every startup** — no manual seeding step.

---

## Deployment (5 minutes)

### Option A: Deploy on Railway (recommended)

1. Fork or clone this repo to your own GitHub account (or use the existing repo URL if you have access).
2. Go to [railway.com/new](https://railway.com/new) → "Deploy from GitHub repo" → pick this repo.
3. Railway auto-detects `railway.json` and `Dockerfile`. Click Deploy.
4. In the project's **Variables** tab, set:

   | Variable | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | Your Anthropic API key (covers classification costs) |
   | `REDDIT_MCP_API_KEYS` | `onramp:sk-onramp-<random-hex>` — generate with `openssl rand -hex 24` |
   | `REDDIT_CLIENT_ID` | From [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) — "script" type |
   | `REDDIT_CLIENT_SECRET` | From the same Reddit app |
   | `REDDIT_USERNAME` | Reddit account username |
   | `REDDIT_PASSWORD` | Reddit account password |
   | `REDDIT_DB_PATH` | `/data/reddit.db` (so the DB survives redeploys) |

5. **Add a persistent volume:** Settings → Volumes → mount at `/data`. Without this, the database resets on every redeploy.
6. **Generate a public URL:** Settings → Networking → "Generate Domain".
7. Done. Hit `https://<your-url>/health` — should return `{"status": "healthy", ...}`.

**Reddit OAuth setup** (5 min, optional but strongly recommended — cloud IPs are often rate-limited by Reddit's public API):
1. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → "create another app"
2. Pick **script**, set redirect URI to `http://localhost:8080` (unused)
3. Use the client ID (under the app name) and the secret in the env vars above

### Option B: Self-host via Docker

```bash
docker build -t onramp-reddit-mcp .
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=... \
  -e REDDIT_MCP_API_KEYS="onramp:sk-onramp-..." \
  -e REDDIT_CLIENT_ID=... \
  -e REDDIT_CLIENT_SECRET=... \
  -e REDDIT_USERNAME=... \
  -e REDDIT_PASSWORD=... \
  -v $(pwd)/data:/data \
  -e REDDIT_DB_PATH=/data/reddit.db \
  onramp-reddit-mcp
```

### Option C: Local-only (one user, on their laptop)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python server.py    # stdio transport, no auth, no public URL
```

Then in Claude Desktop config, use the stdio command form instead of `mcp-remote`.

---

## Connecting Claude to the MCP

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "onramp-reddit": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://YOUR-RAILWAY-URL.up.railway.app/mcp",
        "--header",
        "Authorization:Bearer sk-onramp-YOUR-KEY"
      ]
    }
  }
}
```

Restart Claude Desktop. The 10 `reddit_*` tools should appear in the tool picker.

### Claude Code

```bash
claude mcp add --transport http onramp-reddit \
  https://YOUR-RAILWAY-URL.up.railway.app/mcp \
  --header "Authorization: Bearer sk-onramp-YOUR-KEY"
```

Verify with `claude mcp list`.

### Any other MCP client

The endpoint is `https://YOUR-URL/mcp` over HTTP streaming, with `Authorization: Bearer <key>` header.

---

## Day-one prompts to try

Paste these into Claude after connecting:

1. **Initial scrape**
   > Use the Onramp Reddit MCP to ingest the latest threads from the default subreddits and keywords. Then classify the top 20 threads. Show me the breakdown by priority and topic.

2. **High-priority engagement queue**
   > Search the database for threads from the last 14 days where participation_priority is "urgent" or "high" and the topic involves financing comparisons. For the top 3, generate a participation guide.

3. **Competitive narrative map**
   > Build a narrative map for Payability and Wayflyer. Where are sellers describing Onramp's competitors negatively? Where positively? What pain points come up that Onramp could address better?

4. **Thread origination for Q4 prep**
   > Suggest 5 thread originations targeting amazon_fba_seller persona, focused on Q4 inventory financing. I want titles, full bodies, and target subreddits.

5. **Buyer language mining**
   > Mine buyer language patterns for the dtc_brand_owner persona. What exact phrases do they use to describe their cash flow problems? I want to use these in marketing copy.

6. **peec.ai gap ingestion** (if you export from peec.ai)
   > Use reddit_ingest_urls to load this peec.ai export. Show me threads where AI is citing the thread (citation_count > 30) but Onramp Funds isn't mentioned, ranked by citation count.

---

## Items flagged for Onramp review

The grounding docs contain `[VERIFY: ...]` markers where internal confirmation is needed before public Reddit use:

1. **Fee framing** — site says "2-8% of funded amount" vs. third-party "0.5-2% of gross sales." Which is approved for public Reddit?
2. **Product tiers** — does Onramp offer fixed-repayment / revolving credit-line products beyond pure RBF?
3. **Minimum time in business** — is there one? (competitors require 6-12 months)
4. **Funding range** — confirm $10K-$5M, or different post-credit-facility-expansion?
5. **Speed claim** — "same day" or always "next business day" ACH?
6. **Growth stats** — 60% in 180 days / 80% return rate (current site) vs. 73% / 75% (older site). Which is canonical?
7. **Total funded to merchants to date** — credibility data point if available
8. **Internal escalation contact** for Trustpilot/UCC/legal threads — Eric? Counsel? Comms lead?
9. **White-label / ISO program** for agencies — does this exist?

To update any doc: edit the markdown in `grounding_docs/`, push, redeploy. The startup hook re-seeds on every boot.

---

## Costs to plan for

- **Anthropic API**: classification is ~$0.01-0.03/thread depending on length; participation guides ~$0.05-0.10/thread; thread suggestions ~$0.05-0.10/batch. Budget ~$20-50/month for moderate use.
- **Railway**: $5/month base + usage; expect $5-10/month total for this workload.
- **Reddit OAuth**: free; just need a Reddit account.

---

## Repo structure

```
.
├── server.py                # FastMCP tool definitions (10 tools)
├── server_remote.py         # HTTP wrapper with Bearer auth (Railway entry point)
├── reddit_scraper.py        # Reddit scraping via OAuth API or public JSON
├── classifier.py            # Claude-powered classification + guides
├── db.py                    # SQLite schema, threads + grounding docs
├── seed_grounding_docs.py   # Loads grounding_docs/*.md into DB (auto-runs on startup)
├── grounding_docs/          # The six brand docs — edit these to update positioning
│   ├── competitive_positioning.md
│   ├── voice_tone.md
│   ├── reddit_engagement_rules.md
│   ├── product_messaging.md
│   ├── icp_personas.md
│   └── geo_content_strategy.md
├── Dockerfile
├── railway.json
└── requirements.txt
```

---

## Questions / issues

This MCP is a fork of the Reddit Intelligence MCP originally built for Osano. Code is well-tested in production for the Osano case; the Onramp Funds adaptation is fresh and may need tuning once you see real classification output.
