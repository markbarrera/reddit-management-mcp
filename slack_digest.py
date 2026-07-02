"""Slack daily digest of high-priority community threads (Reddit + Shopify Community).

Runs once a day (via Railway cron, GitHub Action, or `python slack_digest.py`).

Pipeline:
1. Optionally ingest fresh threads (REDDIT_DIGEST_INGEST=1, SHOPIFY_DIGEST_INGEST=1)
2. Classify any unclassified threads
3. Find newly-classified urgent/high priority threads from the last N hours
4. Post a digest to SLACK_WEBHOOK_URL

Environment variables:
- SLACK_WEBHOOK_URL  (required) -- the incoming webhook for the target channel
- DIGEST_LOOKBACK_HOURS  (default 24)
- DIGEST_MAX_THREADS     (default 8) -- cap to avoid Slack message bloat
- REDDIT_DIGEST_INGEST   (default 0) -- set to 1 to scrape Reddit before classifying
- SHOPIFY_DIGEST_INGEST  (default 0) -- set to 1 to scrape Shopify Community before classifying
- REDDIT_DIGEST_CLASSIFY (default 1) -- set to 0 to skip classification step
- DIGEST_CLASSIFY_BATCH_SIZE (default 25) -- total threads classified per run,
  split evenly between Reddit and Shopify Community so neither platform's
  backlog starves the other out (Reddit's upvote-scale scores would
  otherwise dominate a single mixed-platform batch)
- ANTHROPIC_API_KEY      (required if classifying)
- REDDIT_*               (required if ingesting Reddit; see reddit_scraper.py)
"""

import json
import logging
import os
import time

import httpx

from db import get_db
from classifier import classify_batch

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {
    "urgent": ":rotating_light:",
    "high": ":large_orange_diamond:",
    "medium": ":large_blue_diamond:",
}


def _recent_priority_threads(lookback_hours: int, limit: int) -> list[dict]:
    """Return urgent/high threads classified within the lookback window."""
    cutoff = time.time() - (lookback_hours * 3600)
    conn = get_db()
    rows = conn.execute("""
        SELECT thread_id, platform, subreddit, title, url, score, num_comments,
               classification, participation_priority, created_utc
        FROM reddit_threads
        WHERE classification IS NOT NULL
          AND participation_priority IN ('urgent', 'high')
          AND COALESCE(created_utc, 0) >= ?
        ORDER BY
            CASE participation_priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                ELSE 2
            END,
            score DESC
        LIMIT ?
    """, (cutoff, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _community_label(thread: dict) -> str:
    """Human-readable community identifier, platform-aware."""
    if thread.get("platform") == "shopify_community":
        return f"Shopify Community: {thread['subreddit']}"
    return f"r/{thread['subreddit']}"


def _format_thread_block(thread: dict) -> dict:
    """Render a single thread as a Slack Block Kit section."""
    try:
        cls = json.loads(thread.get("classification") or "{}")
    except json.JSONDecodeError:
        cls = {}

    priority = thread.get("participation_priority", "high")
    emoji = PRIORITY_EMOJI.get(priority, ":small_blue_diamond:")
    competitors = [c.get("name") for c in cls.get("entities", {}).get("competitors", [])]
    competitors_str = ", ".join(competitors) if competitors else "none"
    reasoning = cls.get("participation_reasoning", "")
    topic = cls.get("topic", "unknown")
    persona = cls.get("personas", {}).get("thread_author", "unknown")

    title = thread["title"]
    if len(title) > 140:
        title = title[:137] + "..."

    text = (
        f"{emoji} *{priority.upper()}*  |  {_community_label(thread)}  |  "
        f"{thread['score']} upvotes  |  {thread['num_comments']} comments\n"
        f"*<{thread['url']}|{title}>*\n"
        f">_{reasoning}_\n"
        f"`topic: {topic}` `persona: {persona}` `competitors: {competitors_str}`"
    )
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_digest_blocks(threads: list[dict], lookback_hours: int) -> list[dict]:
    """Build Slack Block Kit payload for the digest."""
    if not threads:
        return [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":mag: *Community Intelligence Digest*\n"
                    f"No new urgent or high-priority threads in the last "
                    f"{lookback_hours} hours. The MCP is still scanning."
                ),
            },
        }]

    urgent_count = sum(1 for t in threads if t["participation_priority"] == "urgent")
    high_count = len(threads) - urgent_count

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Community Intelligence Digest -- {len(threads)} threads to review",
            },
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    f"*{urgent_count}* urgent  ·  *{high_count}* high  ·  "
                    f"last {lookback_hours}h  ·  "
                    "ask Claude for a participation guide on any thread below"
                ),
            }],
        },
        {"type": "divider"},
    ]
    for thread in threads:
        blocks.append(_format_thread_block(thread))
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": (
                ":bulb: To act on a thread: in Claude, say "
                "_\"Use the Onramp Reddit MCP to generate a participation "
                "guide for thread <id>\"_"
            ),
        }],
    })
    return blocks


def post_to_slack(webhook_url: str, blocks: list[dict]) -> None:
    """POST the digest payload to the Slack webhook."""
    fallback = "Community Intelligence Digest is ready."
    payload = {"text": fallback, "blocks": blocks}
    resp = httpx.post(webhook_url, json=payload, timeout=30.0)
    resp.raise_for_status()
    logger.info(f"Posted digest to Slack ({len(blocks)} blocks)")


def main() -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        raise SystemExit("SLACK_WEBHOOK_URL is required")

    lookback = int(os.environ.get("DIGEST_LOOKBACK_HOURS", "24"))
    max_threads = int(os.environ.get("DIGEST_MAX_THREADS", "8"))

    if os.environ.get("REDDIT_DIGEST_INGEST", "0") == "1":
        from reddit_scraper import RedditScraper
        from db import upsert_thread, start_scrape_run, complete_scrape_run
        scraper = RedditScraper()
        run_id = start_scrape_run([], [])
        try:
            threads, _ = scraper.scrape_full(limit_per_source=15, fetch_comments=False)
            new = sum(1 for t in threads if upsert_thread(t))
            complete_scrape_run(run_id, len(threads), new)
            logger.info(f"Ingested {len(threads)} Reddit threads ({new} new)")
        finally:
            scraper.close()

    if os.environ.get("SHOPIFY_DIGEST_INGEST", "0") == "1":
        from shopify_scraper import ShopifyCommunityScraper
        from db import upsert_thread, start_scrape_run, complete_scrape_run
        scraper = ShopifyCommunityScraper()
        run_id = start_scrape_run([], [], platform="shopify_community")
        try:
            threads, _ = scraper.scrape_full(limit_per_source=15, fetch_details=False)
            new = sum(1 for t in threads if upsert_thread(t))
            complete_scrape_run(run_id, len(threads), new)
            logger.info(f"Ingested {len(threads)} Shopify Community threads ({new} new)")
        finally:
            scraper.close()

    if os.environ.get("REDDIT_DIGEST_CLASSIFY", "1") == "1":
        # Classify each platform's backlog separately, each with its own
        # slice of the batch budget. A single classify_batch(batch_size=N)
        # call with no platform filter orders candidates by score DESC
        # across both platforms — Reddit's upvote-scale scores are
        # typically much larger than Shopify Community's like_count, so
        # Reddit fills the whole batch first whenever there's any Reddit
        # backlog, and newly-ingested Shopify threads never get classified
        # (silently defeating SHOPIFY_DIGEST_INGEST).
        total_batch = int(os.environ.get("DIGEST_CLASSIFY_BATCH_SIZE", "25"))
        shopify_share = total_batch // 2
        for platform, size in (
            ("reddit", total_batch - shopify_share),
            ("shopify_community", shopify_share),
        ):
            result = classify_batch(batch_size=size, platform=platform)
            logger.info(f"Classified {result.get('classified', 0)} {platform} threads")

    threads = _recent_priority_threads(lookback, max_threads)
    blocks = build_digest_blocks(threads, lookback)
    post_to_slack(webhook, blocks)


if __name__ == "__main__":
    main()
