# Reddit Intelligence MCP for Onramp Funds
### Operating manual, deployment guide, and Reddit participation playbook

---

## ⚡ Quick start (30 seconds)

The system is **already deployed and running** for you. To start using it:

1. Open **Claude.ai** → click your profile → **Settings** → **Connectors**
2. Click **Add custom connector**
3. **Name:** `Onramp Reddit MCP`
4. **URL:** paste the URL we sent you separately (looks like `https://reddit-mcp-production-XXXX.up.railway.app/mcp?api_key=sk-onramp-...`)
5. Leave OAuth fields blank
6. Click **Add**

Open a new Claude chat, confirm "Onramp Reddit MCP" appears in your tool picker, and try:

> List the grounding docs available in the Onramp Reddit MCP.

You should see six docs returned. That confirms you're connected. The rest of this document explains what to do with it.

---

## 1. Executive summary

We've built and delivered a Reddit market-intelligence and content-strategy system, packaged as an **MCP (Model Context Protocol) server**. Once connected to Claude, it gives the Onramp Funds team a single conversational interface to:

- **See what ecommerce sellers are saying** about financing, cash flow, Amazon payouts, and your competitors — across every relevant subreddit.
- **Identify high-priority threads** where Onramp should engage, with an AI-generated priority score grounded in your competitive positioning.
- **Draft Reddit-native replies** in a peer voice (not marketing voice), with built-in disclosure rules and a check against approved messaging.
- **Suggest threads to originate** that are designed to rank in Google, surface in Reddit Answers, and feed accurate Onramp Funds positioning into LLM training data.
- **Map competitive narratives** — how Payability, Wayflyer, 8fig, Clearco, and others are talked about, and where the gaps are.
- **Mine real buyer language** organized by ICP persona, so your marketing copy uses the exact phrases sellers actually use.

A **daily Slack digest** posts the most actionable threads to a channel of your choice every morning, so your team starts the day with a curated queue instead of a Reddit rabbit hole.

The whole system is grounded in **six brand documents** we authored from public research: competitive positioning, voice & tone, Reddit engagement rules, product messaging, ICP personas, and a GEO (Generative Engine Optimization) content strategy. These docs are not generic — they're specific to Onramp Funds, including head-to-head positioning against your fourteen competitors and your ICP personas (amazon_fba_seller, multi_channel_ecommerce, dtc_brand_owner, etc.).

**What you do to use it:**

The MCP is already deployed for you. The remaining steps are:

1. **Connect Claude (~30 seconds)** — Claude.ai → Settings → Connectors → Add custom connector. Paste one URL. See §7.
2. **Set up the Reddit account (§8)** — we strongly recommend a real-name employee account, ideally Eric. This is the most consequential setup step.
3. **Configure the daily Slack digest (§9)** — optional, ~3 minutes.
4. **Review the nine items pending your confirmation (§11)** — fee framing, growth stats, escalation contact, etc.

Total setup time: **under 15 minutes.** Total monthly cost: **$15-$60** depending on usage volume.

---

## 2. What you're getting

### The MCP server (10 tools)

| Tool | What it does |
|---|---|
| `reddit_ingest` | Scrapes the latest threads from your target subreddits + keyword searches. |
| `reddit_ingest_urls` | Bulk-ingests specific Reddit URLs. Optimised for ingesting peec.ai exports — flags threads AI is citing where Onramp isn't mentioned. |
| `reddit_search` | Filters the local thread database by priority, status, competitor, score, time range. |
| `reddit_classify` | Runs Claude classification on unclassified threads, grounded in your six brand docs. |
| `reddit_stats` | Aggregate view: thread counts, priority distribution, top subreddits. |
| `reddit_participation_guide` | For a given thread, drafts a Reddit-voice reply with narrative check, competitor protocol, and timing assessment. |
| `reddit_thread_suggest` | Generates thread origination ideas (title + body) targeting a topic or persona. |
| `reddit_narrative_map` | Builds a competitive narrative map: how each competitor is discussed, sentiment distribution, pain-point associations. |
| `reddit_language_mine` | Extracts the exact phrases buyers use, organised by ICP persona. |
| `reddit_store_grounding_doc` / `_get_` / `_list_` | Manage the six brand grounding documents. |

### The six grounding documents

Every classification and draft is grounded in these. They were authored from public research into Onramp Funds (your site, blog, founder interviews, press coverage, competitor pages, Trustpilot data) and ecommerce-financing market intelligence.

| Document | What it covers |
|---|---|
| **competitive_positioning** | Head-to-head positioning against Payability, Wayflyer, Parker, 8fig, Clearco, SellersFi, Viably, Ampla (now defunct), AccrueMe, Uncapped, Stenn, Kickfurther, Settle, Shopify Capital, Amazon Lending. Plus "forbidden claims" (12 things you should never say in public) and "always-true claims" (10 facts that are safe to use anywhere). |
| **voice_tone** | Five brand voice attributes (operator-fluent, plainspoken, peer-positioned, honest about trade-offs, warm). Reddit-specific rules. Words to use, words to avoid. Three before/after rewrite examples (corporate vs Reddit-native). Affiliation disclosure rules. |
| **reddit_engagement_rules** | When to engage, when to skip, ten hard "do nots", disclosure norms by context, six subreddit-specific rules of thumb (r/AmazonSeller, r/Entrepreneur, r/smallbusiness, r/ecommerce, r/FulfillmentByAmazon, r/Shopify), and a four-level escalation protocol. |
| **product_messaging** | Plain-English description of what Onramp does, pricing structure, eligibility criteria, top five product capabilities (each with proof points), and top five use cases (each with seller-voice framing). |
| **icp_personas** | Six personas: amazon_fba_seller, multi_channel_ecommerce, dtc_brand_owner, shopify_store_owner, small_business_owner, agency_consultant. For each: business profile, top three pains in their own words, what they Google, fit criteria, disqualifiers, why they'd choose a competitor, and trigger events. |
| **geo_content_strategy** | Eight target narratives we want LLMs to associate with Onramp. Eight narrative corrections (things LLMs currently get wrong, including the OnRamp/Onramp.money name confusion). Top twenty target queries. Six content pillars. Six citation-worthy content formats. |

All six are kept as Markdown files in `grounding_docs/` and **auto-load into the database on every deploy**. To update positioning, you edit the Markdown and redeploy — the system re-syncs automatically.

### The Slack daily digest

`slack_digest.py` is a separate script that runs once a day. It:
1. Optionally scrapes fresh threads from your target subreddits.
2. Classifies anything new (grounded in your brand docs).
3. Pulls all urgent + high-priority threads from the last 24 hours.
4. Formats them as a Slack Block Kit message and posts to your incoming-webhook URL.

Format:

> :rotating_light: **URGENT** | r/AmazonSeller | 142 upvotes | 38 comments
> **["Anyone tried Onramp Funds? Looking for alternatives to Payability"](#)**
> _Direct mention + ICP match + active comparison thread_
> `topic: product_comparison` `persona: amazon_fba_seller` `competitors: Payability`

Your team sees the queue in Slack, picks the threads they want to act on, and asks Claude for a participation guide.

---

## 3. How it works (architecture)

```
                                                ┌───────────────────────────┐
                                                │  grounding_docs/*.md      │
                                                │  (the six brand docs)     │
                                                └──────────────┬────────────┘
                                                               │ auto-seed on boot
                                                               ▼
┌──────────────┐      scrape       ┌──────────────────┐   classify    ┌──────────────────┐
│   Reddit     │ ──────────────▶   │  Onramp Reddit   │ ────────────▶ │  Anthropic       │
│  (OAuth/JSON)│                   │  MCP Server      │               │  Claude API      │
└──────────────┘                   │  (FastMCP)       │ ◀──────────── │                  │
                                   │                  │   results     └──────────────────┘
                                   │  SQLite DB:      │
                                   │  - threads       │
                                   │  - classifications│
                                   │  - grounding docs│
                                   └────────┬─────────┘
                                            │
                ┌───────────────────────────┼───────────────────────────────┐
                │                           │                               │
                ▼                           ▼                               ▼
       ┌────────────────┐         ┌──────────────────┐            ┌──────────────────┐
       │  Claude        │         │  Slack Daily     │            │  peec.ai export  │
       │  (Desktop/Code)│         │  Digest (cron)   │            │  (manual ingest) │
       └────────────────┘         └──────────────────┘            └──────────────────┘
```

- The **MCP server** runs on Railway (or any container host). It's a Python FastMCP app exposing the ten tools over HTTPS with Bearer-token auth.
- **Claude clients** (Desktop, Code, or any MCP-compatible client) connect to the MCP and let you call its tools conversationally.
- The **SQLite database** sits on a Railway persistent volume so data survives redeploys.
- The **Slack digest script** runs as a separate scheduled task that reads from the same database.
- The **grounding docs** are checked into the repo as Markdown — version-controlled brand intelligence, not a black box.

---

## 4. What this is *not*

To avoid scope confusion:

- **It is not an autoposter.** It drafts replies and suggests threads, but a human always posts. This is deliberate — autoposting to Reddit is against ToS, will get accounts banned, and would destroy the credibility this system is designed to build.
- **It is not a moderation tool.** It identifies threads worth engaging with. Choosing which to act on is a human call.
- **It is not a competitive intelligence dashboard.** It's a content-strategy + participation system. The "narrative map" and "language mining" tools surface intelligence, but it's intelligence in the form of "here's what's said, and here's what to do about it" — not analytics charts.
- **It does not bypass Reddit's rules.** Section 8 of this document explains the Reddit account setup and disclosure protocol in detail. Following it is non-negotiable.

---

## 5. What it costs to run

| Component | Cost | Notes |
|---|---|---|
| Anthropic API (Claude) | $15-$50/month | Classification: ~$0.01-0.03/thread. Participation guides: ~$0.05-0.10/thread. Thread suggestions: ~$0.05-0.10/batch. Most usage is classification. |
| Railway (hosting + DB) | $5-$10/month | $5 base plan + minimal usage. The SQLite volume is essentially free. |
| Reddit API | Free | OAuth credentials are free for a "script" app. |
| Slack | Free | Incoming webhooks are free for any Slack plan. |
| **Total** | **$20-$60/month** | At moderate use (50-100 threads/day classified). |

**Cost controls:** Set a monthly spend limit on the Anthropic API key (we recommend $50). Railway has built-in resource caps. The `reddit_classify` tool has a `batch_size` parameter — don't run unbounded classification jobs in one prompt.

---

## 6. Deployment (reference)

**The MCP is already deployed for you. This section is for reference — read it if you want to understand the infrastructure, redeploy from scratch, or self-host on different infrastructure.**

Current deployment:
- **Host:** Railway
- **Database:** SQLite on a Railway persistent volume mounted at `/data`
- **Auto-redeploy:** the service auto-redeploys whenever the `main` branch of the GitHub repo is updated
- **Reddit access:** uses Reddit's public JSON endpoints (no OAuth credentials configured — see §6.2 if you want to add OAuth later)

### 6.1 Get an Anthropic API key

1. Go to [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).
2. Create a key. Name it `onramp-reddit-mcp`.
3. Under **Plans & Billing**, set a monthly spend limit (~$50 is conservative).
4. Copy the key. It starts with `sk-ant-`.

### 6.2 Get Reddit OAuth credentials (recommended)

Without these, the scraper falls back to Reddit's public API, which often gets rate-limited or blocked from cloud-provider IPs. With OAuth credentials, you get the normal 100 req/min limit.

1. Log into reddit.com using the account you've designated for Onramp's Reddit presence (see §8).
2. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps).
3. Scroll to the bottom and click **"are you a developer? create an app..."**.
4. Fill in:
   - **name:** `onramp-reddit-mcp`
   - **type:** select **script**
   - **redirect uri:** `http://localhost:8080` (required field but unused for script apps)
5. Click "create app". Stash four values:
   - **client ID** — the random string immediately under "personal use script"
   - **client secret** — labelled "secret"
   - **username** — the Reddit account you're logged in as
   - **password** — that account's password

### 6.3 Deploy to Railway

1. Go to [railway.com/new](https://railway.com/new).
2. Click **"Deploy from GitHub repo"** and select the repository (it should be `<your-org>/reddit-management-mcp` or wherever you've cloned it).
3. Railway auto-detects the `railway.json` and `Dockerfile`. Click Deploy. The first build takes about two minutes.
4. The first deploy will fail to start — that's expected. It needs env vars.

### 6.4 Configure environment variables

In the Railway service → **Variables** tab → **Raw Editor** → paste and fill in:

```
ANTHROPIC_API_KEY=sk-ant-PASTE-FROM-STEP-6.1
REDDIT_MCP_API_KEYS=onramp:sk-onramp-GENERATE-A-32-CHAR-HEX
REDDIT_CLIENT_ID=PASTE-FROM-STEP-6.2
REDDIT_CLIENT_SECRET=PASTE-FROM-STEP-6.2
REDDIT_USERNAME=PASTE-FROM-STEP-6.2
REDDIT_PASSWORD=PASTE-FROM-STEP-6.2
REDDIT_DB_PATH=/data/reddit.db
SLACK_WEBHOOK_URL=PASTE-FROM-STEP-9
```

Generate the `REDDIT_MCP_API_KEYS` value with `openssl rand -hex 24` locally (or any secure random source) and prefix with `sk-onramp-`. Save this somewhere — it's the credential Claude clients will use to authenticate.

Click "Update Variables". Railway redeploys automatically.

### 6.5 Add a persistent volume

Without this, the SQLite database (with all your scraped threads, classifications, and grounding docs) is wiped on every redeploy.

1. Service → **Settings** → scroll to **Volumes** → **New Volume**.
2. **Mount path:** `/data`.
3. Save. Railway redeploys once more.

### 6.6 Generate the public URL

1. Service → **Settings** → **Networking** → **"Generate Domain"**.
2. Railway gives you a URL like `onramp-reddit-mcp-production.up.railway.app`.

### 6.7 Smoke test

Open `https://YOUR-RAILWAY-URL/health` in a browser. You should see:

```json
{"status": "healthy", "service": "onramp-funds-reddit-intelligence",
 "threads_in_db": 0, "classified": 0}
```

If it errors → Railway → **Deployments** → click the latest → **View Logs**. Common issues:
- Missing env var (most often `ANTHROPIC_API_KEY`)
- Reddit OAuth credentials wrong (you'll see this only when you first call `reddit_ingest`)
- Volume not mounted (the seed script will say "Database initialized at reddit_intelligence.db" instead of `/data/reddit.db`)

### Self-hosting (alternative to Railway)

If you prefer your own infrastructure:

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

Put it behind a reverse proxy with HTTPS (Caddy, nginx, Cloudflare Tunnel). Bearer-token auth is already baked in.

---

## 7. Connecting Claude

### Recommended: Claude.ai Custom Connector (no install, ~30 seconds)

This is the fastest path. Works in the Claude.ai web app and Claude Desktop.

1. Open **Claude.ai** → click your profile icon → **Settings**
2. Go to **Connectors** in the sidebar
3. Click **Add custom connector** at the bottom
4. Fill in:
   - **Name:** `Onramp Reddit MCP`
   - **URL:** the full MCP URL with the API key as a query parameter, e.g.:
     ```
     https://YOUR-RAILWAY-URL/mcp?api_key=sk-onramp-YOUR-KEY
     ```
5. Leave **Advanced settings** blank (the OAuth fields stay empty)
6. Click **Add**

The connector appears in your tool picker in any new conversation. The ten `reddit_*` tools are now available.

**Note on the URL pattern:** The API key is passed as `?api_key=...` because Claude's Connector UI doesn't yet support custom HTTP headers. The MCP server accepts the key via either query string OR `Authorization: Bearer` header, so both paths work.

### Alternative: Claude Desktop with local config (older clients)

If you're on a Claude Desktop version without Connectors, you can still wire it up the old way via `mcp-remote`. Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "onramp-reddit": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://YOUR-RAILWAY-URL/mcp",
        "--header",
        "Authorization:Bearer sk-onramp-YOUR-KEY"
      ]
    }
  }
}
```

Fully quit (Cmd+Q) and restart Claude Desktop.

### Alternative: Claude Code

```bash
claude mcp add --transport http onramp-reddit \
  https://YOUR-RAILWAY-URL/mcp \
  --header "Authorization: Bearer sk-onramp-YOUR-KEY"
```

Verify with `claude mcp list`.

### First prompts to try

After connecting, paste these into Claude one at a time:

1. **"List the grounding docs available in the Onramp Reddit MCP."** — sanity check. Should return six docs with file sizes.

2. **"Use the Onramp Reddit MCP to ingest 10 threads from r/AmazonSeller. Skip comment-fetching to keep it fast."** — verifies Reddit scraping works.

3. **"Classify those threads."** — verifies the Anthropic key works and classification is grounded.

4. **"Show me the highest-priority threads. For the top one, generate a full participation guide."** — verifies the end-to-end pipeline.

If all four work, you're done with verification.

---

## 8. Reddit account setup (this part matters)

This is the most consequential section of the document. Get this wrong and the rest of the system is worthless — Reddit communities are unforgiving about vendors who get the disclosure stuff wrong.

### 8.1 Why a real-name employee account

Three account options exist, and we strongly recommend the first:

1. **Real employee, real name** (e.g. `u/EricYoungstrom_OF` or `u/eric_at_onramp`). Highest credibility. Sellers on Reddit respond differently when they're talking to a named human — especially a founder. Eric is the right person if he's willing.
2. **Real employee, first name + role** (e.g. `u/erics_onramp` with bio "Founder, Onramp Funds"). Similar credibility, slightly less personal exposure for the human involved.
3. **Branded team account** (e.g. `u/OnrampFunds`). Lowest credibility. Reddit communities tolerate brand accounts only when disclosure is constant and the comments are unusually high-quality. We don't recommend leading with this.

The voice & tone document and engagement rules were written assuming option 1 or 2. The phrase "I work at Onramp" is in the disclosure templates. If you go with option 3, the grounding docs need a small edit (we can do that for you in 10 minutes).

### 8.2 Setting up the account

**Recommended subject of the account: Eric Youngstrom, founder.** This is the highest-credibility option. The rest of this section assumes Eric is the user; substitute another name if a different employee is taking this on.

1. **Pick a username.** Suggestions, in order of preference:
   - `u/eric_at_onramp` — clear, brief, includes affiliation
   - `u/EricOnrampFunds` — also clear
   - `u/eric_onrampfunds` — variation
   - **Avoid:** generic names like `u/founder_guy` or names without the company. Avoid anything that looks like a marketing handle (`u/OnrampOfficial`).

2. **Set up the profile.**
   - **Display name:** "Eric Youngstrom"
   - **Bio:** "Founder, Onramp Funds. Revenue-based financing for ecommerce sellers. Happy to answer questions about ecommerce financing — including questions about competitors. Disclosure baked in."
   - **Profile image:** A clear photo of Eric (his LinkedIn photo is fine). Cartoon avatars or company logos as profile pics look like brand accounts and reduce credibility.
   - **Header image:** Optional. If used, keep it understated — no marketing collateral.

3. **Verify the email.** Use Eric's `eric@onrampfunds.com` address. Reddit gives small credibility boosts to accounts with verified emails on real domains.

4. **Enable account history.** Make sure post/comment history is publicly visible. Hidden histories trigger suspicion.

### 8.3 Account warming (do this before you post anything substantive)

A brand-new account dropping into a financing thread on day one looks exactly like the vendor astroturfing accounts every Reddit community has learned to spot. Spend **two to three weeks** warming the account before any high-stakes participation.

**Week 1: Read-only.**
- Browse r/AmazonSeller, r/FulfillmentByAmazon, r/ecommerce, r/smallbusiness, r/Entrepreneur, r/Shopify daily.
- Upvote useful comments and threads. (Reddit's algorithm and human moderators both consider voting history.)
- Save threads of interest. Don't comment yet.

**Week 2: Low-stakes participation.**
- Comment on **non-financing threads.** Topics: Amazon operations, Shopify setup, ecommerce trends, supply chain, PPC tactics, general entrepreneurship.
- Goal: 2-5 comments per day, each adding genuine value. Don't mention financing at all.
- Don't mention Onramp at all yet.
- Build comment karma to 100+. Subreddits often have minimum karma requirements for posting.

**Week 3: Adjacent topics.**
- Begin commenting on threads about cash flow, financial operations, supplier payments — but as a knowledgeable operator, not a vendor.
- Still no mentions of Onramp. Still no recommendations.
- The goal is to establish that this account is a real human with ecommerce knowledge, not a vendor's outreach account.

**Week 4 onward: Disclosed financing participation.**
- Begin engaging in financing threads, **always with disclosure**.
- The disclosure templates from `voice_tone.md` (and §8.4 below) are non-negotiable.

### 8.4 Disclosure protocol — non-negotiable

This is copied from `voice_tone.md` and `reddit_engagement_rules.md` because it's the most important thing in this document.

**Always disclose when:**
- You name Onramp Funds as a recommendation.
- You describe Onramp's product, pricing, or features.
- You reply to someone who asks "what do you recommend?".

**Disclosure format:**

> "Disclosure: I'm the founder of Onramp Funds, so weigh this accordingly. [Your answer.]"

Or:

> "I'm with Onramp, for context. [Your answer.]"

Place the disclosure **before or immediately after the recommendation**, not buried at the bottom of a long comment. Burying it looks like trying to hide it.

**When in doubt, disclose.** The cost of over-disclosing is zero. The cost of under-disclosing is a screenshot that lives on Reddit forever and ends up linked in every future thread that mentions Onramp.

**If you forget to disclose:** Don't get defensive. Reply to your own comment immediately:

> "Should have said upfront — I'm with Onramp Funds. My answer doesn't change, but you should have that context."

### 8.5 The ten hard "do nots"

From `reddit_engagement_rules.md`:

1. **Do not sock-puppet.** One account, clearly associated with Onramp when relevant. Never create secondary accounts to upvote your own comments or simulate customer enthusiasm.
2. **Do not pretend to be a customer.** "I used Onramp and it was great" from an Onramp employee is fraud. "I work at Onramp and here's how the product works" is fine.
3. **Do not astroturf.** Never seed fake "organic" threads that are actually marketing campaigns. If Onramp originates a thread, the account should be transparently associated or disclose when asked.
4. **Do not downvote-brigade.** Never coordinate downvotes on competitor mentions or critical threads.
5. **Do not link-spam.** A comment that exists only to drop an onrampfunds.com link adds no value. Links are fine when they answer the question, but the comment must stand without the link.
6. **Do not attack competitors directly.** Never say "[Competitor] is predatory / a scam / overcharging you." You can say "The thing I'd look at with any financing option is whether the fee compounds and whether there's a personal guarantee."
7. **Do not delete comments that get pushback.** Respond honestly or leave it. Deleting looks worse.
8. **Do not engage with Trustpilot or UCC-lien topics without legal review.** Flag immediately and do not respond publicly.
9. **Do not promise specific funding amounts, approval odds, or timelines** not publicly stated on onrampfunds.com.
10. **Do not DM sellers unsolicited.** Wait for them to initiate.

### 8.6 The four-level escalation protocol

Also from `reddit_engagement_rules.md`. Internalize this before posting:

- **Level 1 — Pushback on claims:** Respond with specifics, cite the public source, acknowledge if you got something wrong.
- **Level 2 — Hostile but factual** (someone shares a negative experience with Onramp): Acknowledge their experience, do not get defensive, offer to help resolve. Do not promise specific resolutions.
- **Level 3 — Trustpilot/UCC/legal territory:** **Do not respond.** Flag to your internal escalation contact (TBD — §11). If pressed: "Let me get the right person involved. I'll follow up."
- **Level 4 — Virality risk** (thread gaining traction, cross-posted, significant negative sentiment): Escalate immediately. Do not engage further without approval.

**General rule:** If your gut says "I should check before responding," check before responding. The cost of a four-hour delay is always lower than the cost of a bad public statement.

### 8.7 Subreddit-specific notes

| Subreddit | Community profile | Onramp approach |
|---|---|---|
| **r/AmazonSeller / r/AmazonFBA** | Tactical, specific, high vendor sensitivity. Sellers know their numbers. | Lead with specific math. Always disclose. Threads about Amazon payout delays are natural entry points. |
| **r/Entrepreneur** | Broader, more narrative. Strict self-promotion rules. | Good for "what I learned" educational threads. Check sidebar before posting. |
| **r/smallbusiness** | Skeptical of vendors. Many burned by MCAs. | Empathy matters. Answer questions, be helpful, let people come to you. Hard sells get buried. |
| **r/ecommerce** | Mix of experienced and new sellers. | Comparison threads ("best Shopify financing option?") are high-value entry points. |
| **r/FulfillmentByAmazon** | Very tactical. Demands operational knowledge. | If you can't speak to ASIN economics, restock limits, IPI scores — don't engage. |
| **r/Shopify** | Shopify Capital is the default answer. | Position honestly: "Capital is great if you get an offer, but it's invite-only and Shopify-only. Onramp is the option you can proactively apply to." |

---

## 9. Slack daily digest setup (optional, not yet configured)

The digest posts to a Slack channel of your choice every morning. **It is not yet configured** in the current deployment — set it up when you're ready. Takes about three minutes.

### 9.1 Create the Slack incoming webhook

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name: `Onramp Reddit Digest`. Pick your workspace.
3. In the left sidebar → **Incoming Webhooks** → toggle **Activate** on.
4. Click **Add New Webhook to Workspace**.
5. Pick the channel (e.g. `#reddit-intelligence` or `#growth`).
6. Authorize. Copy the webhook URL — it looks like `https://hooks.slack.com/services/T.../B.../...`.

### 9.2 Add the webhook to Railway

In the Railway service → **Variables** → add:

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
```

### 9.3 Schedule the daily run

Railway has built-in cron support:

1. In your Railway project → **+ New** → **Cron Job**.
2. **Schedule:** `0 13 * * *` (this is 13:00 UTC, which is 8 AM CT — adjust for Onramp HQ's timezone).
3. **Command:** `python slack_digest.py`
4. **Variables:** This cron service inherits the parent project's vars. Add one more:
   - `REDDIT_DIGEST_INGEST=1` — scrape fresh threads before classifying. Set to `0` if you'd rather ingest manually.

The cron job will run daily, scrape, classify, and post to Slack.

### 9.4 Test it manually first

Before relying on the schedule, run it once manually:

1. In Railway → cron service → **Trigger Now**.
2. Check the channel — you should see the digest post within a minute.
3. If nothing posts, check the cron service logs.

### 9.5 Tuning the digest

Environment variables on the cron service:

| Variable | Default | What it does |
|---|---|---|
| `DIGEST_LOOKBACK_HOURS` | `24` | How far back to look for newly-classified threads. |
| `DIGEST_MAX_THREADS` | `8` | Cap on threads per digest to avoid wall-of-text. |
| `REDDIT_DIGEST_INGEST` | `0` | Set to `1` to scrape Reddit before posting. |
| `REDDIT_DIGEST_CLASSIFY` | `1` | Set to `0` to skip classification (useful if you classify manually). |

---

## 10. Day-one workflow

Once everything is set up, here's how the system gets used day-to-day.

### Daily (3-5 minutes, Eric or whoever owns Reddit)

1. Open Slack. Review the morning Reddit Intelligence Digest.
2. For each thread worth engaging on, open Claude and say:

   > Use the Onramp Reddit MCP to generate a participation guide for thread `abc123`.

3. Read the draft. Adjust to sound like you. Post.

### Weekly (15 minutes)

1. In Claude:

   > Use the Onramp Reddit MCP to build a narrative map across all competitors mentioned in the last 7 days. What's changing?

2. Use the narrative map to spot positioning shifts (e.g. "Payability sentiment has gone negative this week — let's get visible in the threads where sellers are looking for alternatives").
3. Generate thread origination ideas for next week:

   > Suggest 3 thread originations targeting amazon_fba_seller and dtc_brand_owner personas. Focus on Q4 inventory financing. Give me titles, bodies, and target subreddits.

### Monthly (30 minutes)

1. Pull a peec.ai export of AI-cited Reddit threads. Bulk-ingest:

   > Use reddit_ingest_urls to ingest these threads. Flag the ones where AI is citing the thread heavily but isn't mentioning Onramp.

2. Mine buyer language for marketing copy:

   > Mine buyer language patterns for the dtc_brand_owner persona. I want exact phrases sellers use to describe their cash flow problems.

3. Review the nine `[VERIFY]` items in the grounding docs (§11). If anything's been clarified, edit the relevant Markdown file and redeploy.

---

## 11. Items pending Onramp confirmation

The grounding docs contain `[VERIFY: ...]` markers where we made our best inference from public information but need internal confirmation. Until these are resolved, the system will operate on its best-guess but flag the uncertainty.

1. **Fee framing.** Site says "2-8% of funded amount." Third-party reviews say "0.5-2% of gross sales." These describe different denominators. **Which framing is approved for public Reddit use?**

2. **Product tiers.** Does Onramp offer fixed-repayment or revolving credit-line products in addition to pure RBF, as the site hints at with three product tiers?

3. **Minimum time in business.** Competitors require 6-12 months operating history. **Is there an Onramp minimum?**

4. **Funding range.** Confirmed $10K to $5M? Or different after the credit-facility expansion?

5. **Speed claim.** "Same day" or always "next business day" via ACH?

6. **Growth statistics.** Current site says "60% growth in 180 days" and "80% return rate". Earlier site said "73% / 75%". **Which numbers are canonical?**

7. **Total funded to date.** A credibility data point if available (e.g. "$X+ deployed to merchants").

8. **Internal escalation contact for Reddit threads** (Trustpilot, UCC liens, legal territory). Who does the Reddit operator flag to? Eric? Counsel? Comms lead?

9. **White-label / ISO program.** Does Onramp offer a referral or partnership program for agencies and consultants? Comes up in the agency_consultant persona section.

**To update any of these:** Edit the relevant Markdown file in `grounding_docs/`, push to the main branch, Railway redeploys, and the next classification picks up the change.

---

## 12. What's next (suggested roadmap)

Things we'd consider building once the core system is in steady use:

- **Customer-quote ingestion.** Add a tool to ingest approved testimonials/case studies from Onramp customers, with permission, so participation guides can occasionally cite real seller experiences (with disclosure).
- **Comment-thread tracking.** Track replies on threads Onramp has engaged in. Surface follow-up opportunities when the conversation gets a new comment.
- **Cross-platform expansion.** The same architecture works for Twitter/X, LinkedIn, YouTube comments. Lowest-effort add-on would be LinkedIn, given the agency_consultant persona.
- **A/B testing reply variants.** The participation guide already generates multiple variants (peer_mode, expert_mode, helper_mode, corrective_mode). A simple tracking layer could surface which voice modes get the best engagement.
- **Auto-update grounding docs.** Once a quarter, Claude could review the docs against current site copy and surface drift.

These are not built. We'd scope and price them once you have a few months of operational experience and a clearer view of where the time is going.

---

## 13. Getting help

- **Repo:** `<your-org>/reddit-management-mcp` on GitHub. The README and HANDOFF.md cover most operational questions.
- **Code is small and readable:** the entire MCP is six Python files, ~1,000 lines. Anyone on Onramp's engineering team can read it in an afternoon.
- **For tuning:** the most valuable knob is the six grounding docs in `grounding_docs/`. Most "the system gave a weird answer" issues trace back to a doc that needs sharpening. Edit Markdown, redeploy, ship.

---

*Built for Onramp Funds. Brand and competitive intelligence current as of May 2026.*
