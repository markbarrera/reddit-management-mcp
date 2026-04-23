"""Reddit Intelligence MCP Server.

Brand behavior is defined by the active profile (see profile.py and
profiles/*.yaml). This file contains no brand-specific strings.

Tools:
  Core:
    - reddit_ingest            scrape subreddits + keyword searches
    - reddit_ingest_urls       ingest specific URLs, optionally with
                               citation-tracker metadata (peec, Profound, etc.)
    - reddit_search            filter stored threads
    - reddit_classify          Claude classification with grounding docs
    - reddit_stats             aggregate statistics
  Intelligence:
    - reddit_participation_guide   draft replies with grounding + feedback learning
    - reddit_thread_suggest        originate new threads for rank/citation
    - reddit_narrative_map         competitor narrative analysis
    - reddit_language_mine         buyer-language extraction
    - reddit_citation_gaps         threads AI cites where brand is missing
  Grounding:
    - reddit_store_grounding_doc / reddit_get_grounding_doc / reddit_list_grounding_docs
  Learning:
    - reddit_log_feedback          record original vs final + reason
    - reddit_feedback_history      review past edits
  Profile:
    - reddit_profile_info          introspect active brand profile
"""

import json
import logging
import os
from typing import Optional
from mcp.server.fastmcp import FastMCP

from db import (
    upsert_thread, get_thread, search_threads, get_stats,
    get_unclassified_threads, store_grounding_doc, get_grounding_doc,
    list_grounding_docs, start_scrape_run, complete_scrape_run,
    record_citation, get_citation_gaps,
    log_feedback, get_feedback_history,
)
from reddit_scraper import RedditScraper
from classifier import (
    classify_batch, generate_participation_guide, generate_thread_suggestions,
)
from profile import get_profile

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_profile = get_profile()
mcp = FastMCP(_profile.server_name())


# ============================================
# P0: Core Reddit Tools
# ============================================

@mcp.tool(
    name="reddit_ingest",
    annotations={
        "title": "Scrape Reddit Threads",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def reddit_ingest(
    subreddits: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    time_filter: str = "month",
    limit: int = 25,
    fetch_comments: bool = True,
) -> str:
    """Scrape Reddit threads from subreddits and keyword searches.

    Uses Reddit's public RSS feeds (no auth) or OAuth if credentials set.
    Stores threads in the database and queues them for classification.

    Args:
        subreddits: Subreddits to scrape. Defaults to profile's default_subreddits.
        keywords: Keywords to search across all of Reddit.
            Defaults to profile's default_keywords.
        time_filter: hour, day, week, month, year, all
        limit: Max threads per subreddit/keyword source (1-100)
        fetch_comments: Fetch full comment trees (slower but richer data)
    """
    scraper = RedditScraper()
    run_id = start_scrape_run(subreddits or [], keywords or [])

    try:
        threads, scrape_errors = scraper.scrape_full(
            subreddits=subreddits,
            keywords=keywords,
            time_filter=time_filter,
            limit_per_source=limit,
            fetch_comments=fetch_comments,
        )

        new_count = 0
        updated_count = 0
        for thread in threads:
            is_new = upsert_thread(thread)
            if is_new:
                new_count += 1
            else:
                updated_count += 1

        complete_scrape_run(run_id, len(threads), new_count)

        sample = [
            {"title": t["title"][:80], "subreddit": t["subreddit"], "score": t["score"]}
            for t in sorted(threads, key=lambda x: x.get("score", 0), reverse=True)[:10]
        ]

        result = {
            "threads_found": len(threads),
            "new_threads": new_count,
            "updated_threads": updated_count,
            "subreddits_scraped": list(set(t["subreddit"] for t in threads)),
            "top_threads": sample,
        }
        if scrape_errors:
            result["errors"] = scrape_errors
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Ingest error: {e}")
        return json.dumps({"error": str(e)})
    finally:
        scraper.close()


@mcp.tool(
    name="reddit_ingest_urls",
    annotations={
        "title": "Ingest Reddit Threads by URL",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def reddit_ingest_urls(
    url_data: list[dict],
    fetch_comments: bool = True,
    citation_provider: Optional[str] = None,
) -> str:
    """Ingest specific Reddit threads by URL, optionally with citation metadata.

    Use this to ingest threads from an AI-citation-tracking export
    (peec.ai, Profound, etc.) — threads where AI models are citing sources
    when answering queries in your category.

    Each item in url_data must have a 'url' key, optionally:
      - citation_count: int    — how many times AI cited this thread
      - brand_mentioned: str   — 'Yes', 'No', or 'Unknown'
      - competitors_mentioned: str or list — competitor names
      - (alias) ai_mentioned, peec_competitors are also accepted

    Args:
        url_data: List of dicts; each requires 'url', optionally citation fields
        fetch_comments: Include the comment tree (default True)
        citation_provider: Override provider tag (e.g. 'peec', 'profound').
            Defaults to the profile's configured citation_tracker.provider.
    """
    profile = get_profile()
    provider = (
        citation_provider
        or profile.citation_tracker_provider
        or ("peec" if profile.citation_tracker_enabled else "unknown")
    )

    scraper = RedditScraper()
    new_count = 0
    updated_count = 0
    failed = []
    high_priority_gaps = []

    try:
        for item in url_data:
            url = item.get("url", "")
            if not url:
                failed.append({"url": url, "error": "missing url"})
                continue

            try:
                thread = scraper.fetch_thread_by_url(url)
                if not thread:
                    failed.append({"url": url, "error": "could not fetch or parse"})
                    continue
                if not fetch_comments:
                    thread["comments"] = []

                citation_count = item.get("citation_count")
                brand_mentioned = item.get("brand_mentioned") or item.get("ai_mentioned")
                competitors = item.get("competitors_mentioned") or item.get("competitors") or item.get("peec_competitors")
                if isinstance(competitors, str):
                    competitors = [c.strip() for c in competitors.split(",") if c.strip()]

                is_new = upsert_thread(thread)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

                if citation_count is not None or brand_mentioned or competitors:
                    record_citation(
                        thread_id=thread["thread_id"],
                        provider=provider,
                        citation_count=int(citation_count) if citation_count is not None else None,
                        brand_mentioned=str(brand_mentioned) if brand_mentioned is not None else None,
                        competitors_mentioned=competitors,
                        raw_metadata=item,
                    )

                if (
                    str(brand_mentioned or "").lower() in ("no", "false", "0")
                    and (citation_count or 0) >= 30
                ):
                    high_priority_gaps.append({
                        "thread_id": thread["thread_id"],
                        "title": thread["title"][:80],
                        "subreddit": thread["subreddit"],
                        "citation_count": citation_count,
                        "competitors": competitors,
                    })

            except Exception as e:
                logger.error(f"Error ingesting {url}: {e}")
                failed.append({"url": url, "error": str(e)})
    finally:
        scraper.close()

    result = {
        "urls_provided": len(url_data),
        "new_threads": new_count,
        "updated_threads": updated_count,
        "failed": len(failed),
        "citation_provider": provider,
        "high_priority_gaps": sorted(
            high_priority_gaps, key=lambda x: x["citation_count"], reverse=True
        ),
    }
    if failed:
        result["failures"] = failed[:20]
    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_search",
    annotations={
        "title": "Search Reddit Threads",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_search(
    query: Optional[str] = None,
    subreddit: Optional[str] = None,
    min_score: Optional[int] = None,
    participation_priority: Optional[str] = None,
    participation_status: Optional[str] = None,
    has_competitor: Optional[str] = None,
    time_range_days: Optional[int] = None,
    limit: int = 20,
) -> str:
    """Search stored Reddit threads with rich filtering."""
    profile = get_profile()
    threads = search_threads(
        query=query, subreddit=subreddit, min_score=min_score,
        participation_priority=participation_priority,
        participation_status=participation_status,
        has_competitor=has_competitor, time_range_days=time_range_days,
        limit=limit,
    )

    results = []
    brand_key = profile.brand_slug
    for t in threads:
        entry = {
            "thread_id": t["thread_id"],
            "subreddit": t["subreddit"],
            "title": t["title"],
            "score": t["score"],
            "num_comments": t["num_comments"],
            "url": t["url"],
            "participation_priority": t["participation_priority"],
            "participation_status": t["participation_status"],
        }
        if t.get("classification"):
            try:
                cls = json.loads(t["classification"])
                entry["topic"] = cls.get("topic")
                entry["sentiment"] = cls.get("sentiment", {}).get("overall")
                entry["brand_sentiment"] = (
                    cls.get("sentiment", {}).get(brand_key)
                    or cls.get("sentiment", {}).get("osano")  # legacy fallback
                )
                entry["competitors"] = [
                    c["name"] for c in cls.get("entities", {}).get("competitors", [])
                ]
                entry["thread_author_persona"] = cls.get("personas", {}).get("thread_author")
            except json.JSONDecodeError:
                pass
        results.append(entry)

    return json.dumps({"count": len(results), "threads": results}, indent=2)


@mcp.tool(
    name="reddit_classify",
    annotations={
        "title": "Classify Reddit Threads",
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def reddit_classify(
    thread_ids: Optional[list[str]] = None,
    batch_size: int = 10,
) -> str:
    """Classify Reddit threads using Claude with grounding docs from the active profile."""
    result = classify_batch(batch_size=batch_size, thread_ids=thread_ids)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_stats",
    annotations={
        "title": "Reddit Intelligence Statistics",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_stats(subreddit: Optional[str] = None) -> str:
    """Aggregate statistics about stored Reddit data."""
    stats = get_stats(subreddit=subreddit)
    return json.dumps(stats, indent=2)


# ============================================
# P1: Intelligence Tools
# ============================================

@mcp.tool(
    name="reddit_participation_guide",
    annotations={
        "title": "Generate Participation Guide",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def reddit_participation_guide(thread_id: str) -> str:
    """Generate a participation recommendation for a thread.

    Injects grounding docs + recent human edits (from reddit_log_feedback)
    so drafts improve week over week.
    """
    result = generate_participation_guide(thread_id)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_thread_suggest",
    annotations={
        "title": "Suggest Thread Origination",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def reddit_thread_suggest(
    topic: Optional[str] = None,
    persona: Optional[str] = None,
    template: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Generate thread origination suggestions.

    Templates available are declared in the profile's taxonomy.thread_templates.
    """
    suggestions = generate_thread_suggestions(topic=topic, persona=persona, limit=limit)
    return json.dumps(suggestions, indent=2)


@mcp.tool(
    name="reddit_narrative_map",
    annotations={
        "title": "Build Competitive Narrative Map",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_narrative_map(competitor: Optional[str] = None) -> str:
    """Build competitive narrative analysis from classified Reddit conversations."""
    threads = search_threads(has_competitor=competitor, limit=100)

    if not threads:
        return json.dumps({
            "message": "No classified threads with competitor mentions found. "
                       "Run reddit_ingest and reddit_classify first."
        })

    narrative_data = {}
    for t in threads:
        if not t.get("classification"):
            continue
        try:
            cls = json.loads(t["classification"])
            for comp in cls.get("entities", {}).get("competitors", []):
                name = comp["name"]
                if competitor and name.lower() != competitor.lower():
                    continue
                if name not in narrative_data:
                    narrative_data[name] = {"mentions": 0, "sentiments": [], "contexts": [], "pain_points": []}
                narrative_data[name]["mentions"] += 1
                narrative_data[name]["sentiments"].append(comp.get("sentiment", "neutral"))
                if comp.get("context"):
                    narrative_data[name]["contexts"].append(comp["context"])
            for pp in cls.get("pain_points", []):
                for comp_name in narrative_data:
                    if comp_name.lower() in t.get("full_text", "").lower():
                        narrative_data[comp_name]["pain_points"].append(pp)
        except json.JSONDecodeError:
            continue

    result = {}
    for name, data in narrative_data.items():
        sentiments = data["sentiments"]
        result[name] = {
            "total_mentions": data["mentions"],
            "sentiment_distribution": {s: sentiments.count(s) for s in set(sentiments)},
            "sample_contexts": data["contexts"][:10],
            "associated_pain_points": list(set(data["pain_points"]))[:10],
        }

    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_language_mine",
    annotations={
        "title": "Mine Buyer Language Patterns",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_language_mine(
    persona: Optional[str] = None,
    topic: Optional[str] = None,
) -> str:
    """Extract buyer language patterns from classified threads."""
    threads = search_threads(query=topic, limit=100)
    if not threads:
        return json.dumps({"message": "No classified threads found."})

    all_pain = []
    all_lang = []
    persona_language = {}

    for t in threads:
        if not t.get("classification"):
            continue
        try:
            cls = json.loads(t["classification"])
            author_persona = cls.get("personas", {}).get("thread_author", "unknown")
            if persona and author_persona != persona:
                continue
            if author_persona not in persona_language:
                persona_language[author_persona] = {
                    "pain_points": [], "buyer_phrases": [], "thread_count": 0,
                }
            persona_language[author_persona]["thread_count"] += 1
            persona_language[author_persona]["pain_points"].extend(cls.get("pain_points", []))
            persona_language[author_persona]["buyer_phrases"].extend(cls.get("buyer_language", []))
            all_pain.extend(cls.get("pain_points", []))
            all_lang.extend(cls.get("buyer_language", []))
        except json.JSONDecodeError:
            continue

    for p in persona_language.values():
        p["pain_points"] = list(set(p["pain_points"]))[:20]
        p["buyer_phrases"] = list(set(p["buyer_phrases"]))[:20]

    return json.dumps({
        "total_threads_analyzed": len(threads),
        "by_persona": persona_language,
        "all_pain_points": list(set(all_pain))[:30],
        "all_buyer_phrases": list(set(all_lang))[:30],
    }, indent=2)


@mcp.tool(
    name="reddit_citation_gaps",
    annotations={
        "title": "Find AI-Citation Content Gaps",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_citation_gaps(
    provider: Optional[str] = None,
    min_count: int = 30,
    limit: int = 50,
) -> str:
    """Find Reddit threads where AI models cite competitors but NOT the brand.

    Requires citation data imported via reddit_ingest_urls. These are the
    highest-leverage threads to either comment on or counter with originated
    threads of your own.

    Args:
        provider: Filter by tracker source (e.g. 'peec', 'profound')
        min_count: Minimum AI citation count to include
        limit: Max results
    """
    gaps = get_citation_gaps(provider=provider, min_count=min_count, limit=limit)
    return json.dumps({"count": len(gaps), "gaps": gaps}, indent=2)


# ============================================
# Grounding Document Tools
# ============================================

@mcp.tool(
    name="reddit_store_grounding_doc",
    annotations={
        "title": "Store Grounding Document",
        "readOnlyHint": False,
        "idempotentHint": True,
    }
)
async def reddit_store_grounding_doc(
    doc_key: str,
    title: str,
    content: str,
    doc_type: str = "reference",
    source_url: Optional[str] = None,
) -> str:
    """Store a grounding document for classification and response generation.

    Common doc_keys: competitive_positioning, voice_tone, icp_personas,
    product_messaging, engagement_rules, content_strategy. The profile's
    grounding_doc_keys controls which get injected into prompts.
    """
    store_grounding_doc(doc_key, title, content, doc_type, source_url)
    return json.dumps({
        "stored": doc_key,
        "title": title,
        "doc_type": doc_type,
        "size": len(content),
    })


@mcp.tool(
    name="reddit_get_grounding_doc",
    annotations={
        "title": "Get Grounding Document",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_get_grounding_doc(doc_key: str) -> str:
    """Retrieve a grounding document by key."""
    content = get_grounding_doc(doc_key)
    if content:
        return content
    return json.dumps({"error": f"Grounding doc '{doc_key}' not found"})


@mcp.tool(
    name="reddit_list_grounding_docs",
    annotations={
        "title": "List Grounding Documents",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_list_grounding_docs() -> str:
    """List all stored grounding documents."""
    docs = list_grounding_docs()
    return json.dumps(docs, indent=2)


# ============================================
# Feedback / Learning Tools
# ============================================

@mcp.tool(
    name="reddit_log_feedback",
    annotations={
        "title": "Log Edit Feedback",
        "readOnlyHint": False,
        "idempotentHint": False,
    }
)
async def reddit_log_feedback(
    tool_name: str,
    original_output: str,
    final_version: str,
    reason: str,
    thread_id: Optional[str] = None,
    user_name: Optional[str] = None,
    outcome: Optional[str] = None,
) -> str:
    """Record what was actually used vs what the MCP drafted, and why.

    These logs are retrieved as few-shot examples for future draft generation,
    making the system learn team preferences over time.

    Args:
        tool_name: Which tool produced the original (e.g. 'reddit_participation_guide')
        original_output: Exact text of the original draft
        final_version: The version that was actually used/posted
        reason: WHY it was changed (e.g. "too formal", "removed CTA", "added caveat about eligibility")
        thread_id: Related thread, if applicable
        user_name: Team member who edited (e.g. 'mark'). Omit for anonymous.
        outcome: Optional post-outcome note (e.g. "+12 upvotes", "deleted by mods")
    """
    feedback_id = log_feedback(
        tool_name=tool_name,
        original_output=original_output,
        final_version=final_version,
        reason=reason,
        thread_id=thread_id,
        user_name=user_name,
        outcome=outcome,
    )
    return json.dumps({"logged": True, "feedback_id": feedback_id})


@mcp.tool(
    name="reddit_feedback_history",
    annotations={
        "title": "Review Feedback History",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_feedback_history(
    tool_name: Optional[str] = None,
    user_name: Optional[str] = None,
    subreddit: Optional[str] = None,
    limit: int = 50,
) -> str:
    """Review past edit feedback. Use this to audit what the team has been
    changing, spot patterns, and decide whether grounding docs need updating."""
    rows = get_feedback_history(tool_name=tool_name, user_name=user_name, subreddit=subreddit, limit=limit)
    return json.dumps({"count": len(rows), "feedback": rows}, indent=2)


# ============================================
# Profile Introspection
# ============================================

@mcp.tool(
    name="reddit_profile_info",
    annotations={
        "title": "Active Brand Profile",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
async def reddit_profile_info() -> str:
    """Return the active brand profile (brand name, defaults, taxonomy, compliance).
    Useful for verifying which profile is loaded and what the server is
    configured to focus on."""
    p = get_profile()
    return json.dumps({
        "source_path": str(p.source_path),
        "brand": p.brand,
        "defaults": p.defaults,
        "taxonomy": p.taxonomy,
        "grounding_doc_keys": p.grounding_doc_keys,
        "compliance": {
            "disclaimer_required": p.disclaimer_required,
            "guardrails_count": len(p.compliance_guardrails),
        },
        "integrations": {
            "citation_tracker": {
                "enabled": p.citation_tracker_enabled,
                "provider": p.citation_tracker_provider,
            },
        },
    }, indent=2)
