# Reddit Intelligence MCP

A brand-configurable Model Context Protocol server for Reddit market
intelligence, participation guidance, and AI-citation optimization.

Point it at a YAML profile for your brand and you get a full toolkit to:

- **Monitor** — scrape relevant subreddits and keyword searches into a
  local SQLite database
- **Classify** — tag each thread (topic, sentiment, persona, competitor
  mentions) using Claude + your grounding docs
- **Participate** — generate draft replies grounded in your voice, product
  messaging, and compliance rules
- **Originate** — suggest new threads designed to rank in Google and get
  cited by AI engines
- **Learn** — record how your team edits drafts, and future drafts
  improve based on those edits
- **Analyze** — competitor narrative maps, buyer-language mining,
  AI-citation gap analysis

Nothing in this codebase is hardcoded to a specific brand. Everything
brand-specific lives in a profile YAML and grounding Markdown docs.

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Copy the example profile and edit for your brand
cp profiles/example.yaml profiles/mybrand.yaml
$EDITOR profiles/mybrand.yaml
export MCP_PROFILE_PATH=$(pwd)/profiles/mybrand.yaml

# 3. Add grounding docs as .md files, then seed them
mkdir -p grounding
$EDITOR grounding/competitive_positioning.md
$EDITOR grounding/voice_tone.md
# ... one .md per key declared in your profile's grounding_doc_keys
python scripts/seed_grounding.py grounding/

# 4. Set your API keys
export ANTHROPIC_API_KEY=sk-ant-...
export REDDIT_CLIENT_ID=...       # optional but recommended
export REDDIT_CLIENT_SECRET=...
export REDDIT_USERNAME=...
export REDDIT_PASSWORD=...

# 5. Start the server
python server_remote.py
```

Check it's up: `curl http://localhost:8000/health`

## Profile structure (at a glance)

A profile is a single YAML file with these sections. See
[`profiles/example.yaml`](profiles/example.yaml) for a fully-commented
template.

| Section | What it controls |
|---|---|
| `brand` | Name, slug, industry one-liner, URL |
| `defaults` | Subreddits to watch, keywords to search, known competitors, supported platforms |
| `taxonomy` | The enums the classifier is allowed to use: topics, personas, thread templates, response variants |
| `grounding_doc_keys` | Which Markdown docs to inject into every LLM prompt |
| `narrative_check_fields` | Brand-specific checks every draft must address |
| `compliance` | Hard rules + a `required_disclaimer` string that must appear verbatim in drafts touching pricing/eligibility |
| `integrations.citation_tracker` | Ingest AI-citation metadata (peec.ai, Profound, custom) |
| `prompts` | Optional role-line overrides for each prompt type |

## The tools

All exposed as MCP tools. In Claude Code / Cursor / Claude Desktop, you
call them as normal.

| Tool | Purpose |
|---|---|
| `reddit_ingest` | Scrape subreddits + keyword searches |
| `reddit_ingest_urls` | Ingest specific URLs, optionally with AI-citation metadata |
| `reddit_search` | Filter stored threads by subreddit, priority, competitor, etc. |
| `reddit_classify` | Classify threads with Claude using your grounding docs |
| `reddit_stats` | Aggregate stats |
| `reddit_participation_guide` | Draft replies (with learned preferences from past edits) |
| `reddit_thread_suggest` | Suggest new threads to originate |
| `reddit_narrative_map` | Competitor narrative analysis |
| `reddit_language_mine` | Extract buyer language patterns |
| `reddit_citation_gaps` | Threads AI cites where your brand is missing |
| `reddit_store_grounding_doc` | Write a grounding doc directly |
| `reddit_get_grounding_doc` | Read a grounding doc |
| `reddit_list_grounding_docs` | List all grounding docs |
| `reddit_log_feedback` | Record human edits so future drafts learn |
| `reddit_feedback_history` | Audit past edits |
| `reddit_profile_info` | Introspect the active profile |

## The learning loop

When your team edits a draft reply before posting, log the edit:

```python
# Inside your Claude/Cursor session, after tweaking a draft:
reddit_log_feedback(
    tool_name="reddit_participation_guide",
    original_output="<the draft the MCP produced>",
    final_version="<what you actually posted>",
    reason="removed the CTA and added an eligibility caveat",
    thread_id="abc123",
    user_name="alice",   # comes from your Bearer token, set below
    outcome="+18 upvotes, no mod action",
)
```

Next time `reddit_participation_guide` runs for a similar thread, up to
five relevant past edits are injected into the prompt as few-shot examples.
The model applies those patterns automatically. No retraining required.

## Team deployment (multi-user auth)

Each team member gets their own Bearer token. Set:

```bash
export REDDIT_MCP_API_KEYS="alice:sk-alice-xxx,bob:sk-bob-yyy,scheduler:sk-ops-zzz"
```

The name before the colon shows up in logs and can be passed to
`reddit_log_feedback(user_name=...)` for per-user audit trails.

## Deployment

`Dockerfile` ships working defaults. To point at your profile at deploy time:

```dockerfile
# Option A — bake profile into image
COPY profiles/mybrand.yaml /app/profiles/active.yaml
ENV MCP_PROFILE_PATH=/app/profiles/active.yaml

# Option B — mount at runtime
docker run -v /host/path/mybrand.yaml:/app/profiles/active.yaml \
  -e MCP_PROFILE_PATH=/app/profiles/active.yaml \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e REDDIT_MCP_API_KEYS="alice:...,bob:..." \
  -p 8000:8000 reddit-intelligence-mcp
```

## Environment variables

| Var | Required | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API access for classification/drafts |
| `MCP_PROFILE_PATH` | Recommended | Absolute path to your brand profile YAML |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USERNAME` / `REDDIT_PASSWORD` | Optional | Enables OAuth (required if hosting on a cloud whose IPs Reddit blocks from public endpoints) |
| `REDDIT_MCP_API_KEYS` | Recommended for teams | Comma-separated `name:key` pairs for Bearer-token auth |
| `REDDIT_DB_PATH` | Optional | SQLite path, defaults to `./reddit_intelligence.db` |
| `CLASSIFIER_MODEL` | Optional | Claude model ID, defaults to `claude-sonnet-4-5-20250929` |
| `PORT` | Optional | HTTP port, defaults to `8000` |
| `LOG_LEVEL` | Optional | Python logging level, defaults to `INFO` |

## Repository layout

```
.
├── server.py             # MCP tool definitions (brand-neutral)
├── server_remote.py      # ASGI wrapper with Bearer auth
├── profile.py            # YAML profile loader
├── prompts.py            # Prompt templates parameterized by profile
├── classifier.py         # Claude classification + participation + origination
├── reddit_scraper.py     # Reddit RSS/OAuth scraping
├── db.py                 # SQLite schema + all data access
├── profiles/
│   └── example.yaml      # Commented profile template
├── grounding/            # Shared Markdown grounding docs (.md per key)
├── scripts/
│   └── seed_grounding.py # Load .md files into the grounding_docs table
└── private/              # GITIGNORED — put brand-specific profiles and
                          # grounding docs here. Never commits.
```

## License

MIT — see [LICENSE](LICENSE).
