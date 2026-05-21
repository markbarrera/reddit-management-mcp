# Onramp Reddit MCP — Phase 2 Roadmap

For Onramp Funds leadership. A plan for what to build on top of the Phase 1 Reddit Intelligence MCP, organized by strategic value rather than engineering effort.

---

## Strategic frame

Your stated goal is **not Reddit referral traffic**. It's **brand perception in LLMs** — when a seller asks ChatGPT, Claude, Perplexity, or Gemini "what's the best financing option for my Amazon business?", Onramp Funds should appear in the answer, correctly positioned.

Reddit is one input to that goal. LLMs cite Reddit threads heavily when answering ecommerce questions because Reddit is in their training data and in their live retrieval. So:

- **A high-quality Reddit comment from Onramp** has compounding value: it influences the conversation today, gets indexed by Google tomorrow, and becomes a training signal for the next generation of LLMs.
- **A negative or AI-tell-laden Reddit comment** has compounding damage for the same reasons.
- **Direct Reddit referral traffic is a side benefit**, not the metric.

This frame reshapes what's worth building. Below is Phase 2 ordered by impact on this goal.

---

## Current state (Phase 1) — what's been built and deployed

The MCP server is **already running** on Railway and connected to Claude.ai via Custom Connector. Below is the complete inventory of what's live, organized by capability.

### Core MCP server (deployed, in production)

- **FastMCP-based HTTP server** with Bearer-token auth, hosted on Railway, SQLite database on a persistent volume
- **Eleven tools** available to Claude clients:
  - `reddit_ingest` — scrape subreddits and keyword searches with parallelized comment fetching
  - `reddit_ingest_urls` — bulk-ingest specific Reddit URLs with optional peec.ai-style citation metadata
  - `reddit_search` — query the local thread database with rich filtering
  - `reddit_classify` — Claude-powered classification with 8-way concurrency (grounding-doc-aware)
  - `reddit_stats` — aggregate statistics across the database
  - `reddit_participation_guide` — drafts a Reddit-voice reply with disclosure, competitor protocol, and a subreddit-specific calibration
  - `reddit_thread_suggest` — generates thread origination ideas (titles + bodies) per persona/topic
  - `reddit_narrative_map` — competitive narrative analysis across the database
  - `reddit_language_mine` — extracts the exact phrases buyers use, organized by ICP persona
  - `reddit_subreddit_profile` — combines DB aggregation with live Reddit subreddit metadata (rules, subscriber count, sidebar)
  - `reddit_purge_offtopic` — cleans up off-topic noise from broad keyword searches, with dry-run safety
  - Plus grounding-doc CRUD: `reddit_store_grounding_doc`, `reddit_get_grounding_doc`, `reddit_list_grounding_docs`
- **Two authentication paths** for compatibility: Bearer header (used by Claude Desktop, Claude Code, mcp-remote) and `?api_key=` query parameter (used by Claude.ai Custom Connector, which does not yet support custom headers)
- **Auto-deploy from GitHub main** — Onramp can push edits to grounding docs and they ship within ~2 minutes without manual intervention
- **Persistent SQLite database** mounted at `/data` so threads, classifications, and grounding docs survive every redeploy

### Grounding documents (the brand intelligence layer)

Six markdown documents authored from public research and live-iterated based on actual Reddit output testing:

- **`competitive_positioning.md`** — head-to-head positioning against Payability, Wayflyer, Parker, 8fig, Clearco, Clearbanc, SellersFunding, SellersFi, Viably, Ampla, AccrueMe, Uncapped, Stenn, Kickfurther, Settle, Shopify Capital, Amazon Lending. Plus twelve "forbidden claims" and ten "always-true claims" for safe public use.
- **`voice_tone.md`** — five brand voice attributes, mandatory formatting rules (no em-dashes, no bold mid-comment, no AI-tell phrases, 150-250 word cap), a rewrite test, and a reference comment that hits the target register exactly. Tightened after the first live participation guide produced AI-sounding output.
- **`reddit_engagement_rules.md`** — when to engage and skip, ten hard "do nots," disclosure protocols by context, six subreddit-specific rules of thumb, and a four-level escalation protocol.
- **`product_messaging.md`** — plain-English product description, eligibility criteria, top five capabilities with proof points, top five use cases with seller-voice framing.
- **`icp_personas.md`** — six ICP personas: `amazon_fba_seller`, `multi_channel_ecommerce`, `dtc_brand_owner`, `shopify_store_owner`, `small_business_owner`, `agency_consultant`. Each with profile, top pains in seller's own words, what they Google, fit criteria, disqualifiers, and trigger events.
- **`geo_content_strategy.md`** — eight target narratives we want LLMs to associate with Onramp, eight narrative corrections (things LLMs currently get wrong), top twenty target queries, six content pillars, six citation-worthy content formats.

All six load into the database automatically on every server boot. Edit the markdown, push to main, the next redeploy syncs them.

### Performance optimizations (shipped after live load testing)

- **Classification concurrency**: ThreadPoolExecutor with eight concurrent Anthropic calls (env-tunable). A batch of 25 threads classifies in roughly 30-50 seconds instead of timing out the MCP transport.
- **Comment-fetch concurrency**: ThreadPoolExecutor with three concurrent Reddit fetches sharing a thread-safe rate limiter. A 25-thread ingest with full comment trees runs in ~15-20s instead of ~50s.
- **Anthropic prompt caching**: Grounding-doc prefixes (~30KB for classification, ~60KB for participation guides) are sent with ephemeral cache markers. First call in a five-minute window is normal speed (cache warm-up). Subsequent calls run 50-70% faster and cost about 90% less in input tokens.
- **Rate limiter**: Reduced minimum interval from 2 seconds to 1 second between Reddit requests (Reddit's actual unauth budget is 60 req/min, so 1s is the real ceiling). Lock-protected so concurrent workers don't race.

### Voice and tone refinements (live-iterated)

Phase 1 included a first deployment of voice_tone.md, then a real-world test exposed AI tells in the generated drafts. Tightening shipped same-day:

- Mandatory formatting rules block placed at the top of the doc (overrides everything else)
- Hard 150-250 word cap on opening comments
- Explicit ban on em-dashes, bold mid-comment, headers, numbered lists with parenthetical labels
- A "Forbidden Phrases" list of AI tells to strip from drafts ("Happy to answer specifics", "At your scale", "Real talk", etc.)
- A "Rewrite Test" checklist the model must run before returning a draft
- A 130-word reference comment showing the target register exactly
- The same critical rules re-stated at the END of the participation guide prompt (where the model is about to generate output), in addition to being in the grounding doc — rules placed just before generation get more model attention than the same rules buried in 60KB of context

### Subreddit intelligence (Layer 1, just shipped)

Every participation guide now automatically calibrates to the community it's posting in:

- DB-aggregated subreddit profile: topic distribution, persona mix of OPs, competitor mentions with sentiment, top-scoring threads, sample low-scoring threads (for "what doesn't work here" signal), all from our own scraping history
- Live Reddit metadata: subscriber count, sidebar description, moderator rules — fetched via public JSON endpoints, no OAuth needed
- The `reddit_subreddit_profile` tool also lets a human ask for this directly: "show me the profile for r/AmazonSeller and compare it to r/Entrepreneur"
- Layer 2 (top contributor identification, voice profiling) is a Phase 2 item, not yet built

### Data hygiene tools

- **`reddit_purge_offtopic`** — broad keyword searches occasionally surface threads from unrelated subreddits (e.g., a search for "financing" picking up r/PrideandPrejudice). This tool deletes threads from subreddits not in an allowlist, with a dry-run preview and built-in protection for any thread already marked urgent/high priority by the classifier. Off-topic noise can be cleaned up without losing real signal.
- **Tightened default keyword list** — removed generic terms that pulled garbage on broad Reddit search ("Parker" alone matched Spider-Man content, "Viably" matched any casual use of the word, "Ampla" is defunct after FundThrough acquisition). Replaced with more specific brand names and multi-word concept phrases.

### Slack digest (built, not yet activated)

A standalone `slack_digest.py` script designed to run as a Railway cron job:

- Pulls newly-classified urgent and high-priority threads from the last 24 hours
- Formats them as a Slack Block Kit message: priority emoji, subreddit, upvotes, comments, title, reasoning, topic/persona/competitors tags
- Posts to a Slack incoming webhook URL
- Configurable lookback window, max threads per digest, optional fresh scrape before posting

Not activated yet because Onramp hasn't created the Slack webhook. Five minutes of setup at api.slack.com/apps when ready.

### Documentation

- **`ONRAMP_HANDOFF.md`** — single-page operating manual that opens with a 30-second Quick Start (Claude.ai Connector setup), then covers architecture, deployment reference, the day-one workflow, the daily/weekly/monthly cadence, the nine `[VERIFY]` items pending Onramp confirmation, costs, and what Onramp owns vs. what is reference-only.
- **`SETUP_BRIEFING.md`** — a self-contained briefing file designed to be pasted into a fresh Claude conversation so Claude can walk a non-engineer through the rest of the setup interactively if needed.
- **This document** — Phase 2 roadmap for leadership.

---

## Phase 2: priorities ranked by impact

### Priority 1 — Connect Profound MCP for AI-citation visibility

**Why:** This closes the loop on the strategic goal. Without it, you're producing Reddit content but flying blind on whether it's translating to AI citations. With it, you can answer: "Three months after we started, how has Onramp's visibility shifted in ChatGPT/Claude/Perplexity? Which of our Reddit posts are actually getting cited?"

**What it looks like in practice:** Onramp installs Profound's MCP server in the same Claude.ai instance alongside the Reddit MCP. A single conversation can now do:

- "Show me which Onramp-related queries in ChatGPT cite Reddit threads. Of those, which subreddits show up most?"
- "Profound says our visibility for 'Amazon FBA financing' dropped 12% last week. Cross-reference with our Reddit activity in r/AmazonSeller to see if there's a content gap we can fill."
- "Generate three Reddit thread ideas (using our existing thread_suggest tool) targeting the queries where Profound shows Onramp visibility is weakest."

**Effort:** Installation only. Onramp already pays for Profound. Connecting it to Claude is a configuration task (~10 min) once you have Profound's MCP endpoint and credentials.

**Owner:** Onramp ops / Eric.

**Risk:** Profound's MCP may have rate limits or feature gaps you'd want to negotiate with their team.

#### Architecture decision: federated vs. co-located data

Once Profound's MCP is connected, a question arises: should Profound's data live alongside Reddit data in our SQLite database, or should each MCP stay in its own lane and let Claude join them at query time?

**Recommendation: start federated, sync selectively as patterns emerge.**

Federated means both MCPs connect to Claude independently. Claude is the joining layer. No integration code, no schema decisions, always-fresh data from each source. Each system stays in its lane and we don't break when either side ships a schema change.

Co-located means we run a daily job that pulls Profound data into our local database. Single source of truth, faster queries, server-side joins possible. But: an ETL pipeline to maintain, schema decisions, sync timing, data staleness, and a brittle coupling to Profound's API shape that breaks when they iterate.

The honest tradeoff is that **Claude is good at the join**. Asking "use Reddit MCP to find our highest-engagement subreddits and Profound MCP to find our weakest AI-citation queries, then correlate" works perfectly in a single Claude conversation with both MCPs connected. Building a pipeline to do the same correlation server-side is overkill until you know which correlations are routine enough to automate.

**The phased approach:**

| Month | Action |
|---|---|
| Months 1-2 | Both MCPs federated to Claude. No sync. Use them together in conversations. Observe which cross-system queries become routine. |
| Months 2-3 | Two or three query patterns will emerge as "we ask this every Monday." Those are the patterns worth automating. Build a daily sync of *only* the Profound metrics those queries need. Not all of Profound — just the subset. |
| Month 3+ | The Slack digest gets enriched with the synced AI-citation data ("top urgent Reddit threads, plus our AI visibility shifted X% in queries Y and Z over the weekend"). The engagement quality tracker (Priority 2) can correlate Reddit comments to AI citation movement on related queries. |

**One exception worth doing immediately:** if Onramp wants long-term archival of their AI visibility scores (in case Profound ever changes retention policy), a lightweight daily snapshot of *just* the per-engine visibility numbers is cheap and high-value. One row per engine per day, ~30 rows/day total, trivial to store. A `track_ai_visibility` table with columns `date, engine, metric, value`. Can ship in a day once Profound API credentials are available.

**The anti-pattern to avoid:** trying to mirror all of Profound into our database from day one. That builds the wrong subset, couples tightly to a v1 schema, and over-engineers before knowing what's valuable.

---

### Priority 2 — Engagement quality tracking (the "learning loop")

**Why:** Phase 1 produces drafts. Phase 2 closes the feedback loop by tracking what actually worked when posted, so the next draft is calibrated to reality.

**What gets tracked:**

- Each comment Onramp posts (logged via a new `reddit_log_engagement` tool)
- The comment's score over time (re-fetched on a schedule)
- Replies to the comment (sentiment, who's responding, do they ask follow-ups)
- Whether moderators removed it
- Per-subreddit averages (which response variants — peer/expert/helper/corrective — get upvoted where)

**What you learn after 30-60 days of data:**

- "r/AmazonSeller upvotes our 'expert mode' responses 2x more than 'helper mode'"
- "Our comments score lower when they mention specific competitor names — keep mentions but use the category phrasing instead"
- "Mod removal rate in r/Entrepreneur is 23% — we need to study their self-promotion rules more carefully"
- "Threads where our reply is among the top 3 comments generate 4x more click-throughs to onrampfunds.com (combined with §4 attribution)"

**What this enables in the system:** Claude can periodically review the engagement data and propose updates to voice_tone.md and reddit_engagement_rules.md. Human approves the changes. The grounding docs become living artifacts that learn from real outcomes.

**Effort:** ~1 week of engineering. New DB table, three new MCP tools (`reddit_log_engagement`, `reddit_refresh_engagement`, `reddit_engagement_report`), modified Slack digest to surface engagement trends.

**Owner:** Contractor or Onramp engineer.

**Trigger to start:** 30 days after Onramp begins posting regularly.

---

### Priority 3 — Subreddit intelligence Layer 2 (top contributors, voice profiling)

**Why:** Phase 1's per-subreddit profiles use *our* scraped history. Layer 2 adds *real community voice profiling* — who are the credibility-holders in each target sub, what do they sound like, how can our drafts match that register.

**What gets built:**

- For each priority subreddit (~10), scrape the top 20 most-upvoted commenters of the last 90 days
- Sample 5 of their recent comments per person
- Have Claude summarize: "This commenter writes in [tone], uses [vocabulary patterns], engages with [topics]. Tolerant of vendor disclosure? Y/N based on patterns."
- Store as a per-subreddit voice profile and inject into participation guides

**Impact:** Drafts feel more native to each community because they're pattern-matching against actual high-credibility voices, not just static rules.

**Effort:** ~3-5 days. Reddit rate limits will be a constraint — likely need to set up OAuth credentials at this point (the same fight we punted on in Phase 1).

**Owner:** Contractor or Onramp engineer.

**Risk:** Reddit may block Railway IPs more aggressively when we're doing user-history fetching at scale. May require a proxy service ($20-50/mo).

---

### Priority 4 — Lead attribution mechanism

**Why:** You said Reddit may not drive direct referral traffic in measurable volume, but leads DO mention "I heard about you on Reddit" on sales calls. Without a capture mechanism, this signal is lost and you can't quantify Reddit's actual impact on pipeline.

**This is a process and CRM task, not engineering.** The MCP system can't fix it; Onramp's RevOps/marketing team does.

**Recommended capture points:**

1. **Application form field:** Add "How did you hear about us?" as a required dropdown on onrampfunds.com's application form. Options: Google, Reddit, ChatGPT/Claude/Perplexity (combined "AI assistant"), Word of mouth, Newsletter, Other. Free-text "Tell us more" optional.
2. **Sales call protocol:** Sales team asks "How did you find Onramp?" on every discovery call. Logs to CRM with subreddit name if applicable.
3. **UTM convention for Reddit links:** When Onramp does link to onrampfunds.com in a Reddit comment (per engagement rules, only when relevant), use `?utm_source=reddit&utm_medium=comment&utm_campaign=[subreddit_name]`. GA4 captures this even if conversion is delayed.
4. **CRM "source: Reddit" enrichment:** When the form captures Reddit as source, RevOps tags the deal record. Standard CRM enrichment.

**What this gives you:** A monthly report showing "X% of new applicants cited Reddit as their discovery source. Conversion rate of Reddit-sourced leads vs. baseline. Pipeline value attributable to Reddit activity."

**Effort:** ~1 day of marketing-ops work. No code from this MCP project.

**Owner:** Onramp marketing-ops / RevOps.

**Combine with Priority 2** (engagement tracking) and you have an end-to-end picture: which Reddit comments → which subreddits → which lead types → which deals.

---

### Priority 5 — Cross-platform expansion

**Why:** LLMs cite Reddit heavily, but they also cite LinkedIn, YouTube comments, Twitter/X, podcasts, and industry blogs. The Phase 1 architecture (scrape → classify → guide → draft) generalizes to any of these.

**Most valuable adjacent platform:** LinkedIn. Reasons:

- LinkedIn is where ecommerce sellers' agencies, consultants, and 7-8 figure operators hang out
- Long-form LinkedIn posts get cited by AI assistants for B2B queries
- The `agency_consultant` ICP persona we already defined lives there
- Onramp's executives can post and have it amplified — Reddit can't do that

**What it would look like:** A `linkedin_*` set of MCP tools paralleling our Reddit tools. Different scraping mechanism (LinkedIn doesn't expose the same public API; would need either Sales Navigator access or a third-party data provider like PhantomBuster). Same classification + guide architecture.

**Effort:** ~2-3 weeks. LinkedIn data access is the hard part, not the AI/MCP layer.

**Owner:** Contractor.

**Trigger to start:** After Reddit is generating consistent value (engagement data + AI citation movement) for 2-3 months.

---

### Priority 6 — Competitor playbook tracker

**Why:** Payability, Wayflyer, 8fig, Settle, and Clearco all play this game too. Knowing what they're doing in real time lets Onramp counter-position.

**What it tracks:**

- Identify the Reddit accounts of Payability/Wayflyer/etc. team members (when they disclose, which they often do)
- Track every public comment they make: which subreddits, what voice, what positioning
- Surface in the Slack digest: "Payability just posted in r/AmazonSeller defending their pricing — here's the thread, here's the angle we could counter with"

**Effort:** ~1 week. Reuses most of the existing scraper infrastructure.

**Owner:** Contractor.

**Caveat:** Need to be careful about implementation looking like surveillance. Public posts are public, but the optics of "we monitor every Payability comment in real-time" could backfire if exposed. Recommend framing internally as "competitive intelligence", limiting access to a small team, and never referencing it externally.

---

## Phase 3+ ideas (further out)

Tracked here for completeness, not recommended for next 6 months:

- **Auto-update grounding docs from learned patterns** — Claude reviews engagement data quarterly and proposes voice_tone.md edits. Human approves.
- **Sentiment monitoring beyond Reddit** — Trustpilot scrape, news mentions, podcast transcripts.
- **Founder-led content recommendations** — when Eric should post personally vs. when an employee account should respond.
- **A/B testing reply variants** — programmatically split-test peer_mode vs expert_mode vs corrective_mode and track which wins per subreddit.
- **Automated thread origination scheduling** — given the GEO content strategy, propose a calendar of threads to originate over 90 days.

---

## What to measure (suggested KPIs)

Tied to the strategic frame.

### Primary KPIs (the goal)

- **AI visibility (from Profound):** Onramp's share-of-voice in target queries across ChatGPT, Claude, Perplexity, Gemini. Track weekly.
- **AI citation rate (from Profound):** % of Onramp-relevant AI responses that cite a source. Of those citations, % from Reddit threads we've influenced.
- **Branded query volume (from Google Search Console):** are people searching "Onramp Funds" more, post-Reddit-activity? Lagging but meaningful.

### Secondary KPIs (the inputs)

- **Reddit threads we've engaged with per week** (from MCP stats)
- **Average comment score on our posts** (from Priority 2 once built)
- **Mod removal rate** (from Priority 2)
- **% of new applicants citing Reddit/AI assistants as source** (from Priority 4)

### Sanity-check metrics (the negatives)

- **Trustpilot/UCC mentions on Reddit** — early warning system. Slack digest should flag any thread mentioning these.
- **Account bans/warnings** — if it happens once, it's a wake-up call. Hopefully zero.

---

## Recommended sequencing (6-month view)

| Month | Focus |
|---|---|
| **Month 1** | Hand off Phase 1, warm Reddit account, post first ~15 comments using existing tools. **Connect Profound MCP** in parallel. |
| **Month 2** | Continue posting (~30-50 comments). Capture leads via Priority 4 (form + sales protocol). Begin lead attribution. |
| **Month 3** | Trigger engagement-tracking build (Priority 2). Start capturing per-comment scores and replies. |
| **Month 4** | Engagement data is meaningful. Begin Layer 2 subreddit intelligence (Priority 3) for the 3-5 highest-value subreddits. |
| **Month 5** | First quarterly review. Update grounding docs based on engagement data. Decide on LinkedIn expansion (Priority 5). |
| **Month 6** | If LinkedIn approved, begin Priority 5. Otherwise continue scaling Reddit and adding competitor tracking (Priority 6). |

---

## Estimated cost and effort

| Priority | Engineering effort | New infra cost | Owner |
|---|---|---|---|
| 1. Profound MCP | ~0 (config only) | $0 (already paid) | Onramp ops |
| 2. Engagement loop | ~1 week | $0 | Contractor or in-house |
| 3. Subreddit Layer 2 | ~3-5 days | ~$20-50/mo proxy if blocked | Contractor |
| 4. Lead attribution | ~1 day (no code) | $0 | Onramp RevOps |
| 5. LinkedIn expansion | ~2-3 weeks | $50-200/mo data access | Contractor |
| 6. Competitor tracker | ~1 week | $0 | Contractor |

Total Phase 2 engineering: roughly **5-6 weeks** spread over **3-6 months**.

---

## Open questions for Onramp leadership

Before committing to any Phase 2 item, answers needed:

1. **Profound credentials:** Does Onramp have an MCP endpoint URL or API access from Profound? If yes, we can wire it up immediately. If no, who at Onramp owns that vendor relationship?
2. **Engagement-loop budget:** Is Onramp committing to engineering hours for this, or is it staying with contractors?
3. **Lead attribution:** Who at Onramp owns marketing ops / RevOps? They're the right person to wire up the form and sales-call capture.
4. **Reddit account strategy:** Is Eric the named Reddit voice, or another employee? This affects who's available to actually post the drafts we generate (and who shoulders the personal exposure).
5. **Competitor tracking ethics:** Comfortable with the framing in Priority 6, or want to scope it down to "track only publicly disclosed competitor employee accounts" with formal documentation?
6. **Cross-platform appetite:** Is LinkedIn (or Twitter/X) on the radar in 2026, or is Reddit-only the explicit Phase 2 scope?

---

*This roadmap is a starting point. The right next step depends on whether early Reddit results validate the strategic frame, which we'll know after 30-60 days of consistent activity.*
