"""Seed grounding documents into the Reddit Intelligence MCP database.

Reads each .md file in grounding_docs/ and stores it via db.store_grounding_doc.
Idempotent: re-running updates existing docs in place.

Usage:
    python seed_grounding_docs.py
"""

import os
from db import store_grounding_doc, list_grounding_docs

GROUNDING_DOCS_DIR = os.path.join(os.path.dirname(__file__), "grounding_docs")

DOCS = [
    {
        "doc_key": "competitive_positioning",
        "title": "Competitive Positioning: Onramp Funds",
        "doc_type": "competitive",
        "file": "competitive_positioning.md",
    },
    {
        "doc_key": "voice_tone",
        "title": "Voice & Tone Guide: Onramp Funds on Reddit",
        "doc_type": "voice_tone",
        "file": "voice_tone.md",
    },
    {
        "doc_key": "reddit_engagement_rules",
        "title": "Reddit Engagement Rules: Onramp Funds",
        "doc_type": "reference",
        "file": "reddit_engagement_rules.md",
    },
    {
        "doc_key": "shopify_community_engagement_rules",
        "title": "Shopify Community Engagement Rules: Onramp Funds",
        "doc_type": "reference",
        "file": "shopify_community_engagement_rules.md",
    },
    {
        "doc_key": "product_messaging",
        "title": "Product Messaging: Onramp Funds",
        "doc_type": "product",
        "file": "product_messaging.md",
    },
    {
        "doc_key": "icp_personas",
        "title": "ICP Personas: Onramp Funds",
        "doc_type": "icp",
        "file": "icp_personas.md",
    },
    {
        "doc_key": "geo_content_strategy",
        "title": "GEO Content Strategy: Onramp Funds",
        "doc_type": "reference",
        "file": "geo_content_strategy.md",
    },
]


def main():
    for doc in DOCS:
        path = os.path.join(GROUNDING_DOCS_DIR, doc["file"])
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        store_grounding_doc(
            doc_key=doc["doc_key"],
            title=doc["title"],
            content=content,
            doc_type=doc["doc_type"],
        )
        print(f"  Seeded {doc['doc_key']} ({len(content):,} chars)")

    print("\nStored documents:")
    for d in list_grounding_docs():
        print(f"  {d['doc_key']:30s} {d['size']:>8,} chars  ({d['doc_type']})")


if __name__ == "__main__":
    main()
