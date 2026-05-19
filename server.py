"""Onramp Funds Reddit Intelligence MCP Server.

Provides tools for Reddit scraping, classification, participation guidance,
thread origination, narrative analysis, and language mining — all grounded
in Onramp Funds' brand knowledge and competitive strategy.
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
)
from reddit_scraper import RedditScraper
from classifier import (
    classify_batch, generate_participation_guide, generate_thread_suggestions,
)

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

mcp = FastMCP("onramp_funds_reddit_mcp")


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

    Uses Reddit's public JSON endpoints (no API key needed).
    Stores threads in database and queues them for classification.

    Args:
        subreddits: List of subreddits to scrape (e.g. ["AmazonSeller", "ecommerce"]).
            Defaults to: AmazonSeller, FulfillmentByAmazon, Amazon_FBA, ecommerce,
            smallbusiness, Entrepreneur, shopify, EcomTrade
        keywords: Keywords to search across all of Reddit (e.g. ["Onramp Funds", "FBA financing"]).
            Defaults to: ecommerce financing, Amazon seller financing, FBA financing,
            inventory financing, revenue based financing, Onramp Funds, Payability,
            Wayflyer, Parker financing, 8fig, Clearco, SellersFunding, Viably, Ampla, AccrueMe
        time_filter: Time range for search — hour, day, week, month, year, all
        limit: Max threads per subreddit/keyword source (1-100)
        fetch_comments: Whether to fetch full comment trees (slower but richer data)

    Returns:
        JSON summary with thread counts, new vs updated, and sample thread titles
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

        # Sample titles for response
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
) -> str:
    """Ingest specific Reddit threads by URL, with optional peec.ai citation metadata.

    Use this to ingest threads from your monthly peec.ai export — threads that
    AI models are actively citing when answering ecommerce financing queries.

    Each item in url_data must have a 'url' key, and can optionally include:
      - citation_count: int — how many times AI cited this thread (from peec.ai 'Used total')
      - ai_mentioned: str — 'Yes', 'No', or 'Unknown' (from peec.ai 'Mentioned')
      - competitors: str or list — competitor names mentioned (from peec.ai 'Mentions')

    Example url_data:
      [
        {"url": "https://www.reddit.com/r/AmazonSeller/comments/abc123/...", "citation_count": 97, "ai_mentioned": "No", "competitors": "Payability, Wayflyer"},
        {"url": "https://www.reddit.com/r/ecommerce/comments/xyz789/...", "citation_count": 65, "ai_mentioned": "No"}
      ]

    Args:
        url_data: List of dicts — each requires 'url', optionally 'citation_count',
            'ai_mentioned', and 'competitors'
        fetch_comments: Whether to include the comment tree (default True)

    Returns:
        JSON summary with ingested count, failures, and high-priority gaps found
    """
    scraper = RedditScraper()
    new_count = 0
    updated_count = 0
    failed = []
    high_priority_gaps = []  # ai_mentioned=No + high citation_count

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

                # Attach peec.ai metadata
                citation_count = item.get("citation_count")
                ai_mentioned = item.get("ai_mentioned")
                competitors = item.get("competitors")

                if citation_count is not None:
                    thread["citation_count"] = int(citation_count)
                if ai_mentioned is not None:
                    thread["ai_mentioned"] = str(ai_mentioned)
                if competitors is not None:
                    if isinstance(competitors, str):
                        thread["peec_competitors"] = [
                            c.strip() for c in competitors.split(",") if c.strip()
                        ]
                    else:
                        thread["peec_competitors"] = competitors

                is_new = upsert_thread(thread)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Flag high-priority gaps: AI not citing Onramp Funds + highly cited thread
                if (
                    str(ai_mentioned or "").lower() in ("no", "false", "0")
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
        "high_priority_gaps": sorted(
            high_priority_gaps, key=lambda x: x["citation_count"], reverse=True
        ),
    }
    if failed:
        result["failures"] = failed[:20]  # Cap to avoid huge responses
    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_search",
    annotations={
        "title": "Search Reddit Threads",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
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
    """Search Reddit threads in the database with rich filtering.

    Combines full-text search with structured classification filters.

    Args:
        query: Text search across thread titles, bodies, and comments
        subreddit: Filter by subreddit name (without r/ prefix)
        min_score: Minimum Reddit score (upvotes)
        participation_priority: Filter by priority — urgent, high, medium, low, skip
        participation_status: Filter by status — not_engaged, engaged, originated
        has_competitor: Filter for threads mentioning a specific competitor
        time_range_days: Only threads from last N days
        limit: Max results (1-100)

    Returns:
        JSON array of matching threads with classification data
    """
    threads = search_threads(
        query=query,
        subreddit=subreddit,
        min_score=min_score,
        participation_priority=participation_priority,
        participation_status=participation_status,
        has_competitor=has_competitor,
        time_range_days=time_range_days,
        limit=limit,
    )

    results = []
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
                entry["onramp_funds_sentiment"] = cls.get("sentiment", {}).get("onramp_funds")
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
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def reddit_classify(
    thread_ids: Optional[list[str]] = None,
    batch_size: int = 10,
) -> str:
    """Classify Reddit threads using Claude with grounding docs.

    Injects competitive_positioning, icp_personas, and geo_content_strategy
    grounding docs into the classification prompt for strategically-aligned results.

    Args:
        thread_ids: Specific thread IDs to classify. If omitted, classifies
            next batch of unclassified threads.
        batch_size: Number of threads to classify (1-25). Ignored if thread_ids provided.

    Returns:
        JSON summary with classified count, topics, and priorities
    """
    result = classify_batch(batch_size=batch_size, thread_ids=thread_ids)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_stats",
    annotations={
        "title": "Reddit Intelligence Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def reddit_stats(
    subreddit: Optional[str] = None,
) -> str:
    """Get statistics about Reddit data in the database.

    Shows total threads, breakdown by subreddit, classification status,
    participation priorities, and engagement status.

    Args:
        subreddit: Optional filter to show stats for a specific subreddit

    Returns:
        JSON with aggregate statistics
    """
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
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def reddit_participation_guide(
    thread_id: str,
) -> str:
    """Generate a grounded participation recommendation for a Reddit thread.

    Loads ALL 6 grounding docs (competitive positioning, voice/tone,
    engagement rules, product messaging, ICP personas, GEO strategy)
    and generates:
    - Draft response(s) in authentic Reddit voice
    - Narrative check against GEO strategy
    - Competitor response protocol
    - Suggested Onramp Funds content to link
    - Do/don't guidance
    - Timing assessment

    Args:
        thread_id: Reddit thread ID to generate guidance for

    Returns:
        JSON with full participation recommendation
    """
    result = generate_participation_guide(thread_id)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_thread_suggest",
    annotations={
        "title": "Suggest Thread Origination",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
async def reddit_thread_suggest(
    topic: Optional[str] = None,
    persona: Optional[str] = None,
    template: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Generate thread origination suggestions for Reddit.

    Creates fully-drafted thread suggestions designed to rank in Google,
    surface in Reddit Answers, and feed LLM training data with accurate
    Onramp Funds positioning.

    Templates: what_i_learned, honest_comparison, regulatory_explainer,
    myth_busting, resource, ama

    Args:
        topic: Focus on a specific topic (e.g. "FBA inventory financing", "revenue-based vs MCA")
        persona: Target a specific ICP persona (e.g. "amazon_fba_seller", "multi_channel_ecommerce")
        template: Use a specific thread template type
        limit: Number of suggestions to generate (1-10)

    Returns:
        JSON array of thread suggestions with titles, body drafts, and scoring
    """
    suggestions = generate_thread_suggestions(
        topic=topic, persona=persona, limit=limit,
    )
    return json.dumps(suggestions, indent=2)


@mcp.tool(
    name="reddit_narrative_map",
    annotations={
        "title": "Build Competitive Narrative Map",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def reddit_narrative_map(
    competitor: Optional[str] = None,
) -> str:
    """Build competitive narrative analysis from Reddit conversations.

    Analyzes classified threads to map dominant narratives about each brand,
    sentiment distribution, and for Onramp Funds specifically, tracks target
    narratives from the GEO strategy that aren't yet established.

    Args:
        competitor: Specific competitor to analyze (e.g. "Payability", "Wayflyer").
            If omitted, maps all competitors found in threads.

    Returns:
        JSON with narrative maps per brand including frequency and trends
    """
    # Pull all classified threads with competitor mentions
    filter_comp = competitor if competitor else None
    threads = search_threads(has_competitor=filter_comp, limit=100)

    if not threads:
        return json.dumps({"message": "No classified threads with competitor mentions found. Run reddit_ingest and reddit_classify first."})

    # Aggregate narratives from classifications
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
            # Collect pain points
            for pp in cls.get("pain_points", []):
                for comp_name in narrative_data:
                    if comp_name.lower() in t.get("full_text", "").lower():
                        narrative_data[comp_name]["pain_points"].append(pp)
        except json.JSONDecodeError:
            continue

    # Summarize
    result = {}
    for name, data in narrative_data.items():
        sentiments = data["sentiments"]
        result[name] = {
            "total_mentions": data["mentions"],
            "sentiment_distribution": {
                s: sentiments.count(s) for s in set(sentiments)
            },
            "sample_contexts": data["contexts"][:10],
            "associated_pain_points": list(set(data["pain_points"]))[:10],
        }

    return json.dumps(result, indent=2)


@mcp.tool(
    name="reddit_language_mine",
    annotations={
        "title": "Mine Buyer Language Patterns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def reddit_language_mine(
    persona: Optional[str] = None,
    topic: Optional[str] = None,
) -> str:
    """Extract actual buyer language patterns from Reddit threads.

    Organized by persona, returns pain descriptions, evaluation criteria,
    objections, and trigger events — all in the exact words buyers use.

    Args:
        persona: Filter by ICP persona (e.g. "amazon_fba_seller", "multi_channel_ecommerce")
        topic: Filter by topic keyword

    Returns:
        JSON with language patterns organized by category
    """
    threads = search_threads(query=topic, limit=100)

    if not threads:
        return json.dumps({"message": "No classified threads found. Run reddit_ingest and reddit_classify first."})

    all_pain_points = []
    all_buyer_language = []
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
            persona_language[author_persona]["pain_points"].extend(
                cls.get("pain_points", [])
            )
            persona_language[author_persona]["buyer_phrases"].extend(
                cls.get("buyer_language", [])
            )
            all_pain_points.extend(cls.get("pain_points", []))
            all_buyer_language.extend(cls.get("buyer_language", []))
        except json.JSONDecodeError:
            continue

    # Deduplicate
    for p in persona_language.values():
        p["pain_points"] = list(set(p["pain_points"]))[:20]
        p["buyer_phrases"] = list(set(p["buyer_phrases"]))[:20]

    result = {
        "total_threads_analyzed": len(threads),
        "by_persona": persona_language,
        "all_pain_points": list(set(all_pain_points))[:30],
        "all_buyer_phrases": list(set(all_buyer_language))[:30],
    }
    return json.dumps(result, indent=2)


# ============================================
# Grounding Document Tools
# ============================================

@mcp.tool(
    name="reddit_store_grounding_doc",
    annotations={
        "title": "Store Grounding Document",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
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

    Grounding docs are reference documents (competitive positioning, voice/tone,
    product messaging, ICP definitions, etc.) that get injected into Claude prompts
    so analysis is grounded in Onramp Funds' actual standards.

    Args:
        doc_key: Unique key (e.g. 'competitive_positioning', 'voice_tone')
        title: Human-readable title
        content: Full document text
        doc_type: Type — competitive, product, voice_tone, icp, reference
        source_url: Optional source URL

    Returns:
        Confirmation with key and size
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
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def reddit_get_grounding_doc(
    doc_key: str,
) -> str:
    """Retrieve a grounding document by key.

    Args:
        doc_key: Document key (e.g. 'competitive_positioning', 'voice_tone')

    Returns:
        Document content or error if not found
    """
    content = get_grounding_doc(doc_key)
    if content:
        return content
    return json.dumps({"error": f"Grounding doc '{doc_key}' not found"})


@mcp.tool(
    name="reddit_list_grounding_docs",
    annotations={
        "title": "List Grounding Documents",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def reddit_list_grounding_docs() -> str:
    """List all stored grounding documents.

    Returns:
        JSON array of documents with keys, titles, types, and sizes
    """
    docs = list_grounding_docs()
    return json.dumps(docs, indent=2)
