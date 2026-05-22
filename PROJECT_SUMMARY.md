# Onramp Reddit Intelligence MCP — Project Archive

Single-document archive of what was built, why decisions were made, and where everything lives. If everything else gets lost, this doc plus the repo should be enough to reconstitute the project.

---

## Project goal (one sentence)

Help Onramp Funds appear correctly in LLM answers about ecommerce financing by producing high-quality, voice-correct Reddit content at scale, with brand intelligence grounded in real research.

The goal is **not** Reddit referral traffic. It's LLM citation visibility and brand perception. Reddit is one input to that goal because LLMs cite Reddit heavily when answering ecommerce questions.

---

## Production state (as of archive)

| Component | State |
|---|---|
| MCP server | Deployed on Railway, healthy |
| Public URL | `https://reddit-mcp-production-59c2.up.railway.app` |
| Health endpoint | `/health` returns 200 |
| MCP endpoint | `/mcp` (Bearer auth via header OR `?api_key=` query param) |
| Threads in DB | 536 (as of last check) |
| Classified | 95 of 536 (351+ still in queue) |
| Grounding docs loaded | 6 (auto-seed on every boot) |
| Slack digest | Built, not yet activated (no webhook configured) |
| Reddit posting account | Not yet warmed (Onramp to set up) |
| Latest deployed commit | `8df29de` (voice/tone enforcement layer) |

### Access and credentials

| Credential | Where it lives | Notes |
|---|---|---|
| Railway project ID | `8e4dfde6-9fdc-4d05-a892-945bd77590ac` | Mark's Railway account |
| Service ID | `262549ac-ad7a-42b8-8601-cdd6a5f8736e` | Auto-deploys from `main` |
| Volume ID | `35476091-c8a5-4454-91fe-293eb80d1dc1` | Mounted at `/data` |
| Domain ID | `bacb91e4-1180-4fe1-a6d4-326e8d4a7dbc` | Port 8080 target |
| GitHub repo | `markbarrera/reddit-management-mcp` | Default branch: main |
| MCP API key | (in env var `REDDIT_MCP_API_KEYS` on Railway, format `onramp:sk-onramp-...`) | Shared with Onramp to use the MCP |
| Anthropic API key | (in env var `ANTHROPIC_API_KEY` on Railway) | Mark's account, $50/mo cap recommended |
| Reddit OAuth | Not configured (Path A: public endpoints) | Reddit's Devvit funnel blocked us in setup |
| Slack webhook | Not yet created | Onramp creates when ready for daily digest |

---

## Build log (chronological narrative of the work)

This section explains what got built when and why. Read it if you want context on decisions in the codebase that look odd in isolation.

### Stage 1: Fork from the Osano Reddit Intelligence MCP

We started from a working Reddit Intelligence MCP previously built for Osano (a privacy compliance company). Forked the architecture wholesale and swapped:

- Default subreddits: from privacy-related to ecommerce-related (r/AmazonSeller, r/FulfillmentByAmazon, r/ecommerce, r/smallbusiness, r/Entrepreneur, r/shopify, etc.)
- Default keyword list: from privacy/CMP terms to ecommerce financing terms (Onramp Funds, Payability, Wayflyer, 8fig, etc.)
- Classifier prompts and topic enums: from privacy categories to ecommerce financing categories (financing_advice_request, cash_flow_problem, growth_capital, vendor_review, etc.)
- Persona enums: from privacy professional / GRC / etc. to amazon_fba_seller / multi_channel_ecommerce / dtc_brand_owner / shopify_store_owner / small_business_owner / agency_consultant
- Sentiment field: `osano` -> `onramp_funds`
- Branding strings, MCP name, user agent

### Stage 2: Author the six grounding documents

The grounding docs are the actual brand intelligence layer. They were authored from public research (Onramp's site, blog, founder interviews, press, competitor pages, Trustpilot data) and live-iterated based on output testing.

- **competitive_positioning.md**: head-to-head against 14 competitors
- **voice_tone.md**: brand voice + Reddit-specific output rules
- **reddit_engagement_rules.md**: when to engage, hard "do nots", disclosure, escalation
- **product_messaging.md**: what Onramp does, eligibility, capabilities, use cases
- **icp_personas.md**: six ICP personas with pains, fit criteria, triggers
- **geo_content_strategy.md**: LLM citation targets, narrative corrections, target queries

The docs contain nine `[VERIFY]` markers where internal Onramp confirmation is needed (fee framing, product tiers, time-in-business min, funding range, speed claim, growth stats, total funded, escalation contact, white-label program).

### Stage 3: Deployment infrastructure

- Dockerfile + railway.json for one-click Railway deploy
- Auto-seed of grounding docs on every server boot (idempotent)
- SQLite DB on a persistent Railway volume at `/data`
- Bearer-token auth via `REDDIT_MCP_API_KEYS` env var

### Stage 4: Setup attempt and pivots

We attempted Reddit OAuth credentials but Reddit's app-creation flow (the new Devvit funnel + the "Responsible Builder Policy" gate) blocked us multiple times. We pivoted to Path A: use Reddit's public JSON/RSS endpoints which work without authentication.

A separate stress test on a single bad SQLite path (`/data/reddit.db` parent dir not pre-existing) triggered a fix to auto-create the parent directory in `get_db()`.

### Stage 5: Claude.ai Custom Connector compatibility

Original auth was `Authorization: Bearer <token>` header. Claude.ai's Custom Connector UI doesn't yet support custom headers (only OAuth or no-auth). To make the connector flow work for Onramp without requiring `mcp-remote` + JSON config on every machine, we added a second auth path: `?api_key=<token>` query string.

Both auth methods work simultaneously. Header path is preferred for clients that support it (Claude Desktop, Claude Code, mcp-remote). Query-string path enables the simpler Claude.ai Connector flow.

### Stage 6: Performance fixes after live testing

The user ran the system end-to-end, classified 75 threads, and quickly hit timeout walls. Multiple optimizations followed:

1. **Classification parallelization**: Anthropic calls run in a ThreadPoolExecutor with `CLASSIFIER_CONCURRENCY=8` (env-tunable). Each thread independently calls Claude; the main thread does DB writes after results return to avoid SQLite write contention.
2. **Comment-fetch parallelization**: Reddit comment requests in a 3-worker ThreadPoolExecutor sharing a thread-safe rate limiter. Network wait overlaps with rate-limiter wait, cutting wall time roughly 2-3x.
3. **Rate limit tightened**: from 2.0s to 1.0s between Reddit requests (Reddit's actual public-API budget is 60 req/min, so 1s is the real ceiling). Lock-protected so concurrent workers don't race the shared timestamp.
4. **Anthropic prompt caching**: Grounding-doc prefixes (~30KB for classification, ~60KB for participation guides) marked with ephemeral cache. First call in a 5-min window: same speed (warm-up). Subsequent calls within the window: 50-70% faster wall time and ~90% cheaper input tokens.

### Stage 7: Keyword and noise fixes

Broad keyword searches across all of Reddit pulled threads from unrelated subreddits (r/PrideandPrejudice, r/cactiexchange, r/OnePieceScaling). Two responses:

1. **Tightened default keyword list**: removed `Parker` (matches Spider-Man), `Viably` (common adverb), `Ampla` (defunct after FundThrough acquisition), and bare `ecommerce financing` / `working capital ecommerce` (too generic). Added narrower brand and concept queries.
2. **`reddit_purge_offtopic` tool**: deletes threads from subreddits not in an allowlist. Dry-run preview by default. Built-in protection for any thread already classified as urgent/high priority so human-curated value isn't lost.

### Stage 8: Voice/tone iteration after live output testing

First live participation guide produced a 450-word draft full of AI tells: em-dashes, bold mid-comment, numbered lists with parentheticals, phrases like "Happy to answer specifics" and "At your scale". Two rounds of fixes:

**Round 1:**
- Added "Formatting Rules (MANDATORY)" section at top of voice_tone.md
- Word cap 150-250
- Forbidden phrases list (12 AI tells)
- Rewrite test
- Reference comment (130 words, matches target register)
- CRITICAL OUTPUT RULES block at end of participation guide prompt

**Round 2 (after follow-up testing surfaced lingering issues):**
- Renamed to "STOP" block (more attention-grabbing)
- Tightened word cap from 150-250 range to hard 200 cap
- Reframed rewrite test as a 7-item gate ("every item must pass or the draft is not returnable")
- Added explicit PROCEDURE block at the start of guide generation ("re-read STOP rules BEFORE writing each draft, not after")
- Server-side `_check_response_voice` helper that scans each returned draft for word-count overflow, em-dashes, bold markdown, headers, and 11 forbidden phrases. Violations surface in a `voice_warnings` field on the response.

### Stage 9: Subreddit intelligence Layer 1

Participation guides were calibrated to brand docs but not to the specific subreddit being posted in. Layer 1 added:

- `reddit_subreddit_profile(subreddit)` MCP tool: combines DB aggregation (topic distribution, persona mix, competitor sentiment, top-scoring threads, low-scoring threads) with live Reddit metadata (subscriber count, sidebar description, moderator rules via public JSON, no OAuth).
- Auto-injection of the DB-side profile into every `reddit_participation_guide` call so guides are calibrated to the community they'll post in.

Layer 2 (top contributor identification, voice profiling per sub) is a Phase 2 item.

### Stage 10: Documentation deliverables

- `ONRAMP_HANDOFF.md`: leadership-facing operating manual with a 30-second Quick Start at top, full deployment reference, day-one workflow, weekly/monthly cadence, the nine VERIFY items, costs, Reddit persona setup section.
- `ONRAMP_PHASE_2_ROADMAP.md`: six prioritized Phase 2 initiatives ordered by strategic impact, with the federation-vs-co-location architectural decision baked into Priority 1 (Profound integration).
- `SETUP_BRIEFING.md`: self-contained briefing file for paste into a fresh Claude conversation to walk through setup interactively.
- `PROJECT_SUMMARY.md`: this document.

---

## File map

```
reddit-management-mcp/
├── server.py                          # FastMCP tool definitions (13 tools)
├── server_remote.py                   # HTTP wrapper, Bearer + query-string auth, Railway entry point
├── reddit_scraper.py                  # Reddit scraping (public endpoints, parallel comments, locked rate limiter)
├── classifier.py                      # Claude classification + participation guide + thread suggestions, with prompt caching
├── db.py                              # SQLite schema and operations (threads, classifications, grounding docs, scrape runs)
├── seed_grounding_docs.py             # Loads grounding_docs/*.md into DB (runs on every server boot)
├── slack_digest.py                    # Daily Slack digest script (cron-runnable)
├── grounding_docs/
│   ├── competitive_positioning.md
│   ├── voice_tone.md                  # The most-iterated doc; contains the STOP block and rewrite gate
│   ├── reddit_engagement_rules.md
│   ├── product_messaging.md
│   ├── icp_personas.md
│   └── geo_content_strategy.md
├── Dockerfile                         # Python 3.12-slim base, exposes 8000
├── railway.json                       # Railway deploy config
├── requirements.txt                   # mcp, anthropic, httpx, uvicorn, starlette, pydantic
├── README.md
├── HANDOFF.md                         # Original deploy guide (lower-level than ONRAMP_HANDOFF.md)
├── ONRAMP_HANDOFF.md                  # Leadership-facing operating manual
├── ONRAMP_PHASE_2_ROADMAP.md          # Six Phase 2 initiatives with strategic frame
├── SETUP_BRIEFING.md                  # Briefing for handing setup to another Claude session
└── PROJECT_SUMMARY.md                 # This document
```

---

## Key architectural decisions and their rationale

| Decision | Choice | Why |
|---|---|---|
| Reddit OAuth | Skipped (use public endpoints) | Reddit's app-creation flow blocked us twice; public JSON endpoints work fine for low-volume use; OAuth was nice-to-have not blocking |
| Auth method | Bearer header AND query string | Claude.ai Connector UI doesn't support custom headers; we support both so Connector works AND Claude Desktop/Code work |
| Database | SQLite on persistent volume | Operational simplicity; no separate DB service to manage; volume mount survives redeploys |
| Grounding docs storage | Markdown files in repo + auto-seed on boot | Onramp can edit Markdown and push to update brand intelligence; no need to use MCP CRUD tools for routine updates |
| Comment fetching | Parallelized with shared rate limiter | Cuts wall time 2-3x while staying within Reddit's rate budget |
| Classification | Parallelized at 8x concurrency | Same reason; Anthropic comfortably handles 8 concurrent calls |
| Prompt caching | Ephemeral cache on grounding-doc prefix | 50-70% latency reduction + ~90% input cost reduction on cache-hit calls |
| Voice/tone enforcement | Three layers (grounding doc + prompt + server check) | Single-layer enforcement failed live test; redundancy catches model slippage |
| Word count cap | 200 hard (was 150-250 range) | Tighter single number beats a range; LLMs handle hard caps better than ranges |
| Profound integration | Defer; start federated | Don't know which cross-system queries are valuable until 30-60 days of usage; selective sync after observation beats up-front pipeline |
| Per-subreddit intelligence Layer 2 | Defer | Real-Reddit scraping of top contributors needs OAuth or proxy to avoid IP blocking; Layer 1 (DB aggregation + live metadata) covers the immediate need |

---

## Pending items (must do or decide before Onramp goes live with this)

### Owned by Onramp leadership / Eric

1. Confirm fee framing for public Reddit use (`2-8% of funded amount` vs `0.5-2% of gross sales`)
2. Confirm product tiers (just RBF, or also fixed-repayment / revolving credit line?)
3. Confirm minimum time in business (if any)
4. Confirm funding range ($10K-$5M? Or different post credit-facility expansion?)
5. Confirm speed claim (`same day` vs `next business day` ACH)
6. Confirm growth stats (60% / 80% on current site vs 73% / 75% on earlier site)
7. Provide total amount funded to merchants to date (for credibility)
8. Name an internal escalation contact for Trustpilot/UCC/legal Reddit threads
9. Confirm whether Onramp has a white-label or ISO program for agencies

### Owned by Onramp marketing/ops

10. Pick Reddit persona (real-name employee, ideally Eric — affects who actually posts)
11. Warm the Reddit account (read-only week 1, low-stakes commenting week 2, adjacent topics week 3, disclosed financing participation week 4+)
12. Set up Slack incoming webhook if you want the daily digest
13. Add `?utm_source=reddit&utm_medium=comment` UTM convention for any Reddit links
14. Wire up "How did you hear about us?" capture on application form + sales call protocol
15. Decide billing/ownership of Railway + Anthropic accounts (currently on Mark's accounts)

### Owned by contractor (Mark / next engineer)

16. Resolve Reddit OAuth if/when needed (for Layer 2 subreddit intelligence or higher-volume scraping)
17. Build out Phase 2 priorities as triggered by Onramp readiness (see ONRAMP_PHASE_2_ROADMAP.md)

---

## What to do if everything breaks

If the deployment dies or someone needs to start fresh:

1. Repo is at `github.com/markbarrera/reddit-management-mcp` on branch `main`
2. Read `HANDOFF.md` for the Railway deploy steps (env vars, volume mount, domain config)
3. Set the env vars listed under "Access and credentials" above
4. Once `/health` returns 200, the system will auto-seed grounding docs on first boot
5. Connect Claude to the new URL (replace `reddit-mcp-production-59c2.up.railway.app` with the new domain)
6. Re-share the new URL + API key with Onramp

The grounding docs (the actual brand intelligence value) are in version control. Even if the database is wiped, every meaningful Onramp-specific knowledge artifact is recoverable from `grounding_docs/*.md` on `main`.

---

## How to continue this work

If Mark or another contractor picks this up later, the practical paths in order of likely value:

1. **Activate the Slack digest.** Five-minute task. Highest ratio of useful output to setup cost.
2. **Run a fresh, clean ingest.** With tightened keywords and the purge tool, do a clean reset of the DB and re-ingest. Gives a cleaner classification queue.
3. **Connect Profound MCP.** Closes the AI-citation visibility loop. Requires Onramp credentials.
4. **Wait for engagement data, then build the learning loop.** Requires 30-60 days of real Reddit posting first. Roadmap Priority 2.
5. **Subreddit Layer 2.** Top contributors and voice profiles. Requires Reddit OAuth (the saga we punted on).

---

## Final note on accountability

The system was built and verified working end-to-end (deployment, classification, participation guides, subreddit intelligence, voice/tone enforcement) during the build session that produced this archive. Live testing surfaced two real issues (AI tells in drafts, off-topic noise from broad keyword search) which were fixed in the same session.

What was not verified during the build session:
- Sustained Reddit scraping over weeks (potential IP-based blocking from cloud provider IPs)
- Real engagement with Reddit communities (the system can draft, but only humans post)
- Cost trajectory at scale (Anthropic spend should be monitored against the $50/mo cap)

These are real-world risks that will only surface with sustained use. Plan accordingly.
