"""Smoke test: the MCP server must register every expected tool, including
the two added for Shopify Community.
"""

import asyncio

import server

EXPECTED_TOOLS = {
    "reddit_ingest", "reddit_ingest_urls",
    "shopify_ingest", "shopify_ingest_urls",
    "reddit_search", "reddit_classify", "reddit_subreddit_profile",
    "reddit_purge_offtopic", "reddit_stats",
    "reddit_participation_guide", "reddit_thread_suggest",
    "reddit_narrative_map", "reddit_language_mine",
    "reddit_store_grounding_doc", "reddit_get_grounding_doc",
    "reddit_list_grounding_docs",
}


def test_all_expected_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names
