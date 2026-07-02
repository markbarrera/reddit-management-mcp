"""Shopify Community forum scraper using Discourse's public JSON API.

community.shopify.com runs on Discourse. Discourse exposes read data as
plain JSON by appending ".json" to any category or topic URL — no auth
needed for public boards. This mirrors the no-auth-required posture of
reddit_scraper.py, but the concrete endpoints are different.

robots.txt (checked 2026-07-02) explicitly disallows:
  Disallow: /search        -> no keyword search across the forum
  Disallow: /t/*/*.rss     -> no topic RSS
  Disallow: /c/*.rss       -> no category RSS
It does NOT disallow /c/{slug}/{id}.json or /t/{slug}/{id}.json, which is
the sanctioned Discourse API pattern for programmatic read access. This
scraper only ever touches .json endpoints under /c/ and /t/.

Because keyword search is off-limits, there is no search_all() here (unlike
RedditScraper). Discovery is category-based (scrape_category / scrape_full)
or by specific URL (fetch_topic_by_url) for threads found via an external
search (Google site-search, Ahrefs, etc.) — the same pattern reddit_ingest_urls
already uses for peec.ai-sourced Reddit threads.
"""

import os
import re
import time
import html
import logging
import threading
import httpx
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MIN_REQUEST_INTERVAL = float(os.environ.get("SHOPIFY_MIN_REQUEST_INTERVAL", "1.5"))
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0
TOPIC_FETCH_CONCURRENCY = int(os.environ.get("SHOPIFY_TOPIC_CONCURRENCY", "3"))

BASE_URL = "https://community.shopify.com"
DEFAULT_USER_AGENT = "onramp-funds-reddit-intelligence/1.0 (content research)"

# Categories relevant to Onramp's ICP personas (shopify_store_owner,
# dtc_brand_owner, multi_channel_ecommerce). Verified against
# https://community.shopify.com/categories.json on 2026-07-02.
DEFAULT_CATEGORIES = {
    "payments-shipping-fulfilment": 217,
    "accounting-taxes": 223,
    "shopify-discussion": 95,
    "start-a-business": 282,
}


class _CookedTextExtractor(HTMLParser):
    """Extract plain text from Discourse's "cooked" post HTML.

    A naive tag-strip leaves two kinds of junk behind that a plain regex
    can't distinguish from real content:
    - Image embeds render as a "lightbox-wrapper" div containing the image,
      a filename, and a "550x342 21.2 KB" dimensions/size caption. Stripping
      tags alone turns that caption into stray text inline with the reply.
    - Quoted replies render as an "aside.quote" block containing a full
      copy of the post being replied to. Stripping tags alone merges that
      quoted text indistinguishably into the replier's own words, which
      can make the classifier attribute someone else's statement to the
      wrong author.

    Both are dropped by tag/class rather than regexed out, since their
    boundaries are real HTML elements, not a text pattern.
    """

    _SKIPPED_CLASSES = {"quote", "lightbox-wrapper"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_tag: Optional[str] = None
        self._skip_depth = 0

    @staticmethod
    def _classes(attrs: list[tuple[str, Optional[str]]]) -> set[str]:
        for name, value in attrs:
            if name == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag, attrs):
        if self._skip_depth > 0:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if self._classes(attrs) & self._SKIPPED_CLASSES:
            self._skip_tag = tag
            self._skip_depth = 1
            if tag == "div":  # lightbox-wrapper — note an image was here
                self.parts.append(" [image] ")
            return
        if tag in ("p", "br", "li", "blockquote"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self._skip_depth > 0 and tag == self._skip_tag:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.parts.append(data)

    def get_text(self) -> str:
        return "".join(self.parts)


class ShopifyCommunityScraper:
    """Scrape Shopify Community (Discourse) threads via the public JSON API.

    No credentials required for read access to public categories/topics.
    """

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT):
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()
        self.user_agent = user_agent
        self.client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            timeout=30.0,
            follow_redirects=True,
        )

    def _rate_limit(self):
        with self._rate_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < MIN_REQUEST_INTERVAL:
                time.sleep(MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_time = time.time()

    def _request(self, url: str, params: Optional[dict] = None) -> dict:
        """Rate-limited GET with retry/backoff. Returns parsed JSON or {}."""
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                resp = self.client.get(url, params=params)
                if resp.status_code == 429:
                    wait = BACKOFF_FACTOR ** (attempt + 1)
                    logger.warning(f"Rate limited by Shopify Community. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 503:
                    wait = BACKOFF_FACTOR ** (attempt + 1)
                    logger.warning(f"Service unavailable. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 404:
                    logger.warning(f"404 for {url}")
                    return {}
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} for {url}")
                if attempt == MAX_RETRIES - 1:
                    raise
            except httpx.RequestError as e:
                logger.error(f"Request error for {url}: {e}")
                if attempt == MAX_RETRIES - 1:
                    raise
        return {}

    @staticmethod
    def _strip_html(cooked: str) -> str:
        """Convert Discourse's rendered-HTML post body to plain text.

        Uses _CookedTextExtractor rather than a blind tag-strip so that
        image captions and quoted-reply text don't bleed into the result
        as if they were the author's own words (see that class's docstring).
        """
        if not cooked:
            return ""
        extractor = _CookedTextExtractor()
        extractor.feed(cooked)
        text = extractor.get_text()
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()

    @staticmethod
    def _parse_iso(ts: Optional[str]) -> float:
        if not ts:
            return 0.0
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def scrape_category(
        self,
        category_slug: str,
        category_id: int,
        order: str = "activity",
        limit: int = 25,
    ) -> list[dict]:
        """List topics in a category (the board-listing equivalent of
        RedditScraper.scrape_subreddit). Returns stub thread dicts —
        title/counts only, no body/comments yet. Paginates via
        topic_list.more_topics_url until `limit` is reached.

        Args:
            category_slug: Discourse category slug, e.g. "payments-shipping-fulfilment"
            category_id: Discourse category id, e.g. 217
            order: activity, created, likes, views (Discourse sort options)
            limit: Max topics to return
        """
        threads = []
        page = 0
        while len(threads) < limit:
            url = f"{BASE_URL}/c/{category_slug}/{category_id}.json"
            params = {"order": order, "page": page} if page else {"order": order}
            data = self._request(url, params)
            topics = ((data or {}).get("topic_list") or {}).get("topics") or []
            if not topics:
                break
            for t in topics:
                if t.get("pinned") or t.get("archetype") == "banner":
                    continue  # skip pinned "About this category" stickies
                threads.append({
                    "thread_id": f"sc_{t['id']}",
                    "platform": "shopify_community",
                    "subreddit": category_slug,
                    "title": t.get("title", ""),
                    "body": "",  # filled by fetch_topic_by_url/id
                    "author": "",
                    "url": f"{BASE_URL}/t/{t.get('slug', '')}/{t['id']}",
                    "permalink": f"/t/{t.get('slug', '')}/{t['id']}",
                    "score": t.get("like_count", 0),
                    "upvote_ratio": 0.0,
                    "num_comments": t.get("reply_count", 0),
                    "created_utc": self._parse_iso(t.get("created_at")),
                })
                if len(threads) >= limit:
                    break
            more_url = ((data or {}).get("topic_list") or {}).get("more_topics_url")
            if not more_url:
                break
            page += 1
        logger.info(f"Found {len(threads)} topics in c/{category_slug}")
        return threads[:limit]

    def _thread_from_topic_json(self, data: dict, category_slug: str, topic_slug: str, topic_id: int) -> Optional[dict]:
        """Build a thread dict (with comments) from a raw /t/{slug}/{id}.json payload."""
        posts = ((data.get("post_stream") or {}).get("posts")) or []
        if not posts:
            return None
        op = posts[0]
        # Discourse's reply_to_post_number is a per-topic sequential position
        # (1, 2, 3...), a different namespace from the persistent "id" field
        # comments are keyed by. Resolve it through a post_number -> id map
        # so parent_id actually matches another entry's "id" (or the OP's,
        # if a reply targets post_number 1 — the OP isn't itself in
        # `comments`, mirroring how a Reddit comment's parent_id can point
        # at the top-level post rather than another comment).
        post_number_to_id = {
            p.get("post_number"): str(p.get("id", ""))
            for p in posts if p.get("post_number") is not None
        }
        comments = [
            {
                "id": str(p.get("id", "")),
                "author": p.get("username", "[deleted]"),
                "body": self._strip_html(p.get("cooked", "")),
                "score": p.get("score", 0) or 0,
                "parent_id": post_number_to_id.get(p.get("reply_to_post_number"), ""),
                "depth": 0,  # Discourse posts are a flat sequence, not a nested tree
                "created_utc": self._parse_iso(p.get("created_at")),
            }
            for p in posts[1:]
        ]
        return {
            "thread_id": f"sc_{topic_id}",
            "platform": "shopify_community",
            "subreddit": category_slug,
            "title": data.get("title", ""),
            "body": self._strip_html(op.get("cooked", "")),
            "author": op.get("username", "[deleted]"),
            "url": f"{BASE_URL}/t/{topic_slug}/{topic_id}",
            "permalink": f"/t/{topic_slug}/{topic_id}",
            "score": data.get("like_count", 0) or 0,
            "upvote_ratio": 0.0,
            "num_comments": data.get("reply_count", 0) or 0,
            "created_utc": self._parse_iso(data.get("created_at")),
            "comments": comments,
        }

    def fetch_topic(self, category_slug: str, topic_slug: str, topic_id: int) -> Optional[dict]:
        """Fetch full topic detail (OP body + all posts as comments)."""
        data = self._request(f"{BASE_URL}/t/{topic_slug}/{topic_id}.json")
        if not data:
            return None
        return self._thread_from_topic_json(data, category_slug, topic_slug, topic_id)

    def fetch_topic_by_url(self, url: str) -> Optional[dict]:
        """Fetch a single topic by its full Shopify Community URL.

        Works with standard Discourse topic URLs:
          https://community.shopify.com/t/{slug}/{id}[/{post_number}]

        Args:
            url: Full Shopify Community topic URL

        Returns:
            Thread dict with comments, or None if URL is unparseable / fetch fails
        """
        match = re.search(r"/t/([^/]+)/(\d+)", url)
        if not match:
            logger.warning(f"Could not parse Shopify Community topic URL: {url}")
            return None
        topic_slug, topic_id = match.group(1), int(match.group(2))

        data = self._request(f"{BASE_URL}/t/{topic_slug}/{topic_id}.json")
        if not data:
            return None
        # Topic detail includes category_id but not the category slug, so
        # resolve it against known categories; fall back to a synthetic
        # label for boards outside DEFAULT_CATEGORIES (still ingestable,
        # just unlabeled).
        category_id = data.get("category_id")
        category_slug = next(
            (slug for slug, cid in DEFAULT_CATEGORIES.items() if cid == category_id),
            f"category_{category_id}",
        )
        return self._thread_from_topic_json(data, category_slug, topic_slug, topic_id)

    def scrape_full(
        self,
        categories: Optional[dict] = None,
        limit_per_source: int = 25,
        fetch_details: bool = True,
    ) -> tuple[list[dict], list[str]]:
        """Full scrape: category listings + topic detail fetch for each.

        Args:
            categories: {slug: category_id} to scrape. Defaults to DEFAULT_CATEGORIES.
            limit_per_source: Max topics per category
            fetch_details: Whether to fetch full body + posts for each topic
                (a second request per topic; set False for a fast listing-only pass)

        Returns:
            Tuple of (threads list, errors list)
        """
        categories = categories or DEFAULT_CATEGORIES
        seen_ids = set()
        all_threads = []
        errors = []

        for slug, cid in categories.items():
            try:
                stubs = self.scrape_category(slug, cid, limit=limit_per_source)
                for t in stubs:
                    if t["thread_id"] not in seen_ids:
                        seen_ids.add(t["thread_id"])
                        all_threads.append(t)
            except Exception as e:
                msg = f"c/{slug}: {type(e).__name__}: {e}"
                logger.error(f"Error scraping {msg}")
                errors.append(msg)

        if fetch_details and all_threads:
            def _fetch_for(thread):
                match = re.search(r"/t/([^/]+)/(\d+)", thread["permalink"])
                if not match:
                    return thread["thread_id"], None
                topic_slug, topic_id = match.group(1), int(match.group(2))
                try:
                    return thread["thread_id"], self.fetch_topic(
                        thread["subreddit"], topic_slug, topic_id
                    )
                except Exception as e:
                    logger.error(f"Error fetching topic {thread['thread_id']}: {e}")
                    return thread["thread_id"], None

            workers = min(TOPIC_FETCH_CONCURRENCY, max(1, len(all_threads)))
            results = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for tid, detail in pool.map(_fetch_for, all_threads):
                    results[tid] = detail

            merged = []
            for thread in all_threads:
                detail = results.get(thread["thread_id"])
                if detail:
                    merged.append(detail)
                else:
                    thread["comments"] = []
                    merged.append(thread)
            all_threads = merged
        else:
            for thread in all_threads:
                thread["comments"] = []

        logger.info(
            f"Total: {len(all_threads)} unique topics from {len(categories)} categories"
        )
        return all_threads, errors

    def fetch_category_metadata(self, category_slug: str, category_id: int) -> dict:
        """Fetch category description/topic count via the public JSON endpoint.

        Analogous to RedditScraper.fetch_subreddit_metadata — used to
        calibrate participation guidance to the board's own norms.
        """
        result: dict = {"name": category_slug, "category_id": category_id}
        try:
            data = self._request(f"{BASE_URL}/c/{category_id}/show.json")
            cat = (data or {}).get("category") or {}
            if cat:
                result["description"] = (cat.get("description_text") or "")[:2000]
                result["topic_count"] = cat.get("topic_count")
                result["post_count"] = cat.get("post_count")
        except Exception as e:
            logger.error(f"show.json for c/{category_slug}: {e}")
            result["error"] = str(e)
        return result

    def close(self):
        self.client.close()
