# Onramp Funds Reddit Intelligence MCP Server

Reddit market intelligence, participation guidance, and GEO optimization for Onramp Funds — revenue-based financing for ecommerce sellers.

## Setup

```bash
pip install -r requirements.txt
python seed_grounding_docs.py    # one-time: load brand grounding docs into the DB
python server_remote.py
```

## Environment Variables

- `ANTHROPIC_API_KEY` — Required for classification
- `REDDIT_MCP_API_KEYS` — Optional auth (format: `name:key,name2:key2`)
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` — Optional Reddit OAuth (recommended for cloud deployments)
- `PORT` — Default 8000

## Grounding Documents

The MCP relies on six grounding documents injected into classification and response prompts. They live in `grounding_docs/` and are loaded into the database by `seed_grounding_docs.py`:

- `competitive_positioning` — Onramp vs. Payability, Wayflyer, Parker, 8fig, Clearco, etc.
- `voice_tone` — Onramp's brand voice and Reddit posting style
- `reddit_engagement_rules` — Do/don't rules for engaging on Reddit
- `product_messaging` — Product capabilities and approved messaging
- `icp_personas` — Target seller personas (Amazon FBA, multi-channel, DTC, etc.)
- `geo_content_strategy` — Target narratives and queries to win in AI search

Edit the markdown files directly and re-run `python seed_grounding_docs.py` to update. The docs contain `[VERIFY: ...]` markers where Onramp internal confirmation is needed before public Reddit use.
