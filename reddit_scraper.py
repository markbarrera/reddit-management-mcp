"""Reddit scraper using RSS feeds (no auth required) with JSON for comment fetching."""

import os
import re
import time
import json
import logging
import httpx
import xml.etree.ElementTree as ET
from typing import Optional
from datetime import datetime, timezone

ATOM_NS = "{http://www.w3.org/2005/Atom}"

logger = logging.getLogger(__name__)

# Rate limiting
MIN_REQUEST_INTERVAL = 2.0  # seconds between requests
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0

# Default configuration
DEFAULT_SUBREDDITS = [
    "AmazonSeller", "FulfillmentByAmazon", "Amazon_FBA", "ecommerce",
    "smallbusiness", "Entrepreneur", "shopify", "EcomTrade",
]
DEFAULT_KEYWORDS = [
    "ecommerce financing", "Amazon seller financing", "FBA financing",
    "inventory financing", "working capital ecommerce", "revenue based financing",
    "Onramp Funds", "Payability", "Wayflyer", "Parker financing", "8fig",
    "Clearco", "SellersFunding", "Viably", "Ampla", "AccrueMe",
]
DEFAULT_USER_AGENT = "onramp-funds-reddit-intelligence/1.0 (content research)"

# Reddit OAuth token endpoint
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
# Base URL: use oauth.reddit.com when authenticated, www.reddit.com otherwise
REDDIT_PUBLIC_BASE = "https://www.reddit.com"
REDDIT_OAUTH_BASE = "https://oauth.reddit.com"

BRAND_KEYWORDS = [
    "onramp funds", "payability", "wayflyer", "parker", "8fig", "clearco",
    "sellersfunding", "viably", "ampla", "accrueme", "uncapped", "stenn",
    "kickfurther", "settle", "shopify capital", "amazon lending",
]
PRODUCT_KEYWORDS = [
    "revenue based financing", "RBF", "inventory financing",
    "working capital", "merchant cash advance", "ecommerce loan",
    "amazon seller loan", "FBA capital", "inventory loan",
]
REGULATORY_KEYWORDS = [
    "amazon seller fees", "FBA fees", "amazon hold", "amazon reserve",
    "stripe hold", "marketplace payouts",
]
PROBLEM_KEYWORDS = [
    "cash flow problem", "inventory cash flow", "amazon payout delay",
    "scaling inventory", "stockout", "growth capital ecommerce",
    "how to finance inventory",
]


class RedditScraper:
    """Scrape Reddit threads via OAuth API (preferred) or public JSON endpoints.

    Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, and
    REDDIT_PASSWORD to enable OAuth. Without credentials, the scraper falls
    back to the public .json endpoints — which may be blocked by Reddit from
    cloud provider IP ranges.

    To create OAuth credentials:
      1. Go to https://www.reddit.com/prefs/apps
      2. Click "create another app" → choose "script"
      3. Set redirect URI to http://localhost:8080 (unused for script apps)
      4. Copy the client ID (below app name) and client secret
    """

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT):
        self._last_request_time = 0.0
        self._access_token: Optional[str] = None
        self._token_expires: float = 0.0

        # Check for OAuth credentials
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
        username = os.environ.get("REDDIT_USERNAME")
        password = os.environ.get("REDDIT_PASSWORD")

        if client_id and client_secret and username and password:
            self._oauth_enabled = True
            self._client_id = client_id
            self._client_secret = client_secret
            self._reddit_username = username
            self._reddit_password = password
            self._base_url = REDDIT_OAUTH_BASE
            # Reddit requires username in user agent for OAuth apps
            self.user_agent = f"script:onramp-funds-reddit-mcp:1.0 (by /u/{username})"
            logger.info(f"Reddit OAuth enabled — user: u/{username}")
        else:
            self._oauth_enabled = False
            self._base_url = REDDIT_PUBLIC_BASE
            self.user_agent = user_agent
            logger.warning(
                "No Reddit OAuth credentials found (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, "
                "REDDIT_USERNAME, REDDIT_PASSWORD). Using public API — may be blocked from "
                "cloud providers. See scraper docstring for setup instructions."
            )

        self.client = httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

        if self._oauth_enabled:
            self._authenticate()

    def _authenticate(self):
        """Get a Reddit OAuth access token using password grant."""
        import base64
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        resp = httpx.post(
            REDDIT_TOKEN_URL,
            headers={
                "User-Agent": self.user_agent,
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "password",
                "username": self._reddit_username,
                "password": self._reddit_password,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"Reddit OAuth failed: {data}")
        self._access_token = data["access_token"]
        # Expire 60s early to avoid using a stale token
        self._token_expires = time.time() + data.get("expires_in", 3600) - 60
        self.client.headers.update({"Authorization": f"Bearer {self._access_token}"})
        logger.info("Reddit OAuth token acquired")

    def _ensure_authenticated(self):
        """Re-authenticate if the access token has expired."""
        if self._oauth_enabled and time.time() >= self._token_expires:
            logger.info("Reddit OAuth token expired — refreshing...")
            self._authenticate()

    def _rate_limit(self):
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _request(self, url: str, params: Optional[dict] = None) -> dict:
        """Make a rate-limited request with retry and backoff."""
        self._ensure_authenticated()
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                resp = self.client.get(url, params=params)
                if resp.status_code == 429:
                    wait = BACKOFF_FACTOR ** (attempt + 1)
                    logger.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 503:
                    wait = BACKOFF_FACTOR ** (attempt + 1)
                    logger.warning(f"Service unavailable. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                try:
                    return resp.json()
                except Exception as e:
                    # Log raw response so we can see what Reddit actually returned
                    # (e.g. HTML login page, error page, etc.)
                    logger.error(
                        f"JSON decode error for {url}: {e} | "
                        f"status={resp.status_code} | "
                        f"content-type={resp.headers.get('content-type', 'unknown')} | "
                        f"body_preview={resp.text[:300]!r}"
                    )
                    if attempt == MAX_RETRIES - 1:
                        raise
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} for {url}")
                if attempt == MAX_RETRIES - 1:
                    raise
            except httpx.RequestError as e:
                logger.error(f"Request error for {url}: {e}")
                if attempt == MAX_RETRIES - 1:
                    raise
        return {}

    def _request_text(self, url: str, params: Optional[dict] = None) -> str:
        """Make a rate-limited request and return raw response text (for RSS feeds)."""
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                resp = self.client.get(url, params=params)
                if resp.status_code == 429:
                    wait = BACKOFF_FACTOR ** (attempt + 1)
                    logger.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 503:
                    wait = BACKOFF_FACTOR ** (attempt + 1)
                    logger.warning(f"Service unavailable. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} for {url}")
                if attempt == MAX_RETRIES - 1:
                    raise
            except httpx.RequestError as e:
                logger.error(f"Request error for {url}: {e}")
                if attempt == MAX_RETRIES - 1:
                    raise
        return ""

    def _flatten_comments(self, comment_data: dict, depth: int = 0) -> list[dict]:
        """Recursively flatten Reddit's nested comment tree."""
        comments = []
        if not comment_data or not isinstance(comment_data, dict):
            return comments

        children = comment_data.get("data", {}).get("children", [])
        for child in children:
            if child.get("kind") != "t1":  # t1 = comment
                continue
            data = child.get("data", {})
            if not data.get("body") or data.get("body") == "[deleted]":
                continue

            comment = {
                "id": data.get("id", ""),
                "author": data.get("author", "[deleted]"),
                "body": data.get("body", ""),
                "score": data.get("score", 0),
                "parent_id": data.get("parent_id", ""),
                "depth": depth,
                "created_utc": data.get("created_utc", 0),
            }
            comments.append(comment)

            # Recurse into replies
            replies = data.get("replies")
            if replies and isinstance(replies, dict):
                comments.extend(self._flatten_comments(replies, depth + 1))

        return comments

    def _parse_thread_listing(self, data: dict) -> list[dict]:
        """Parse a Reddit listing response into thread dicts."""
        threads = []
        children = data.get("data", {}).get("children", [])
        for child in children:
            if child.get("kind") != "t3":  # t3 = link/post
                continue
            d = child.get("data", {})
            if d.get("is_self") is False and not d.get("selftext"):
                # Skip link-only posts with no text
                pass
            thread = {
                "thread_id": d.get("id", ""),
                "subreddit": d.get("subreddit", ""),
                "title": d.get("title", ""),
                "body": d.get("selftext", ""),
                "author": d.get("author", "[deleted]"),
                "url": f"https://www.reddit.com{d.get('permalink', '')}",
                "permalink": d.get("permalink", ""),
                "score": d.get("score", 0),
                "upvote_ratio": d.get("upvote_ratio", 0.0),
                "num_comments": d.get("num_comments", 0),
                "created_utc": d.get("created_utc", 0),
            }
            threads.append(thread)
        return threads

    def _parse_rss_feed(self, text: str) -> list[dict]:
        """Parse Reddit's Atom RSS feed into thread dicts."""
        if not text:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            logger.error(f"RSS parse error: {e} | preview={text[:200]!r}")
            return []

        threads = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            # Thread ID from <id>t3_abc123</id>
            id_elem = entry.find(f"{ATOM_NS}id")
            raw_id = id_elem.text or "" if id_elem is not None else ""
            thread_id = raw_id.replace("t3_", "") if raw_id.startswith("t3_") else raw_id

            title_elem = entry.find(f"{ATOM_NS}title")
            title = title_elem.text or "" if title_elem is not None else ""

            link_elem = entry.find(f"{ATOM_NS}link")
            url = link_elem.get("href", "") if link_elem is not None else ""
            permalink = url.replace("https://www.reddit.com", "") if url else ""

            author_elem = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
            author_text = author_elem.text or "" if author_elem is not None else ""
            author = author_text.replace("/u/", "").strip()

            cat_elem = entry.find(f"{ATOM_NS}category")
            subreddit = cat_elem.get("term", "") if cat_elem is not None else ""

            content_elem = entry.find(f"{ATOM_NS}content")
            body_html = content_elem.text or "" if content_elem is not None else ""
            body = re.sub(r"<[^>]+>", "", body_html).strip()
            body = (body.replace("&amp;", "&").replace("&lt;", "<")
                    .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))

            updated_elem = entry.find(f"{ATOM_NS}updated")
            created_utc = 0.0
            if updated_elem is not None and updated_elem.text:
                try:
                    dt = datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))
                    created_utc = dt.timestamp()
                except ValueError:
                    pass

            if not thread_id or not title:
                continue

            threads.append({
                "thread_id": thread_id,
                "subreddit": subreddit,
                "title": title,
                "body": body,
                "author": author,
                "url": url,
                "permalink": permalink,
                "score": 0,
                "upvote_ratio": 0.0,
                "num_comments": 0,
                "created_utc": created_utc,
            })
        return threads

    def scrape_subreddit(
        self,
        subreddit: str,
        sort: str = "hot",
        time_filter: str = "month",
        limit: int = 25,
    ) -> list[dict]:
        """Scrape threads from a subreddit.

        Args:
            subreddit: Subreddit name (without r/ prefix)
            sort: hot, new, top, rising
            time_filter: hour, day, week, month, year, all (for top/controversial)
            limit: Max threads to fetch (up to 100 per request)
        """
        url = f"{REDDIT_PUBLIC_BASE}/r/{subreddit}/{sort}.rss"
        params: dict = {}
        if sort in ("top", "controversial"):
            params["t"] = time_filter

        logger.info(f"Scraping r/{subreddit}/{sort} via RSS")
        text = self._request_text(url, params if params else None)
        threads = self._parse_rss_feed(text)
        logger.info(f"Found {len(threads)} threads in r/{subreddit}")
        return threads[:limit]

    def search_subreddit(
        self,
        subreddit: str,
        query: str,
        sort: str = "relevance",
        time_filter: str = "year",
        limit: int = 25,
    ) -> list[dict]:
        """Search within a specific subreddit."""
        url = f"{REDDIT_PUBLIC_BASE}/r/{subreddit}/search.rss"
        params = {"q": query, "restrict_sr": "on", "sort": sort, "t": time_filter}
        logger.info(f"Searching r/{subreddit} for '{query}' via RSS")
        text = self._request_text(url, params)
        threads = self._parse_rss_feed(text)
        logger.info(f"Found {len(threads)} results for '{query}' in r/{subreddit}")
        return threads[:limit]

    def search_all(
        self,
        query: str,
        sort: str = "relevance",
        time_filter: str = "year",
        limit: int = 25,
    ) -> list[dict]:
        """Search across all of Reddit."""
        url = f"{REDDIT_PUBLIC_BASE}/search.rss"
        params = {"q": query, "sort": sort, "t": time_filter}
        logger.info(f"Searching all Reddit for '{query}' via RSS")
        text = self._request_text(url, params)
        threads = self._parse_rss_feed(text)
        logger.info(f"Found {len(threads)} results for '{query}'")
        return threads[:limit]

    def fetch_thread_by_url(self, url: str) -> Optional[dict]:
        """Fetch a single Reddit thread and its comments from a full Reddit URL.

        Parses the URL to extract subreddit and thread ID, then fetches the
        thread JSON endpoint directly. Works with standard Reddit URLs:
          https://www.reddit.com/r/{subreddit}/comments/{thread_id}/...

        Args:
            url: Full Reddit thread URL

        Returns:
            Thread dict with comments, or None if URL is unparseable / fetch fails
        """
        # Extract subreddit and thread_id from URL
        match = re.search(r'/r/([^/]+)/comments/([a-z0-9]+)', url, re.IGNORECASE)
        if not match:
            logger.warning(f"Could not parse Reddit thread URL: {url}")
            return None

        subreddit = match.group(1)
        thread_id = match.group(2)

        json_url = f"{REDDIT_PUBLIC_BASE}/r/{subreddit}/comments/{thread_id}.json"
        params = {"raw_json": 1, "limit": 500}
        logger.info(f"Fetching thread {thread_id} from r/{subreddit}")
        data = self._request(json_url, params)

        if not isinstance(data, list) or len(data) < 1:
            logger.warning(f"No data returned for {thread_id}")
            return None

        # First element is the post listing
        post_listing = data[0]
        children = post_listing.get("data", {}).get("children", [])
        if not children:
            return None

        d = children[0].get("data", {})
        thread = {
            "thread_id": d.get("id", thread_id),
            "subreddit": d.get("subreddit", subreddit),
            "title": d.get("title", ""),
            "body": d.get("selftext", ""),
            "author": d.get("author", "[deleted]"),
            "url": f"https://www.reddit.com{d.get('permalink', '')}",
            "permalink": d.get("permalink", ""),
            "score": d.get("score", 0),
            "upvote_ratio": d.get("upvote_ratio", 0.0),
            "num_comments": d.get("num_comments", 0),
            "created_utc": d.get("created_utc", 0),
            "comments": [],
        }

        # Second element is the comment listing
        if len(data) >= 2:
            thread["comments"] = self._flatten_comments(data[1])

        logger.info(
            f"Fetched thread '{thread['title'][:60]}' "
            f"with {len(thread['comments'])} comments"
        )
        return thread

    def fetch_thread_comments(self, subreddit: str, thread_id: str) -> list[dict]:
        """Fetch full comment tree for a thread."""
        url = f"{REDDIT_PUBLIC_BASE}/r/{subreddit}/comments/{thread_id}.json"
        params = {"raw_json": 1, "limit": 500}
        logger.info(f"Fetching comments for {thread_id} in r/{subreddit}")
        data = self._request(url, params)

        if not isinstance(data, list) or len(data) < 2:
            return []

        comments = self._flatten_comments(data[1])
        logger.info(f"Fetched {len(comments)} comments for {thread_id}")
        return comments

    def scrape_full(
        self,
        subreddits: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        time_filter: str = "month",
        limit_per_source: int = 25,
        fetch_comments: bool = True,
    ) -> tuple[list[dict], list[str]]:
        """Full scrape: subreddit listings + keyword searches + comment fetching.

        Args:
            subreddits: Subreddits to scrape (defaults to DEFAULT_SUBREDDITS)
            keywords: Keywords to search (defaults to DEFAULT_KEYWORDS)
            time_filter: Time range for search
            limit_per_source: Max threads per subreddit/keyword
            fetch_comments: Whether to fetch full comment trees

        Returns:
            Tuple of (threads list, errors list)
        """
        subreddits = subreddits or DEFAULT_SUBREDDITS
        keywords = keywords or DEFAULT_KEYWORDS

        seen_ids = set()
        all_threads = []
        errors = []

        # Scrape subreddit listings
        for sub in subreddits:
            try:
                threads = self.scrape_subreddit(
                    sub, sort="hot", time_filter=time_filter, limit=limit_per_source
                )
                for t in threads:
                    if t["thread_id"] not in seen_ids:
                        seen_ids.add(t["thread_id"])
                        all_threads.append(t)
            except Exception as e:
                msg = f"r/{sub}: {type(e).__name__}: {e}"
                logger.error(f"Error scraping {msg}")
                errors.append(msg)

        # Keyword searches across all Reddit
        for kw in keywords:
            try:
                threads = self.search_all(
                    kw, sort="relevance", time_filter=time_filter, limit=limit_per_source
                )
                for t in threads:
                    if t["thread_id"] not in seen_ids:
                        seen_ids.add(t["thread_id"])
                        all_threads.append(t)
            except Exception as e:
                msg = f"search '{kw}': {type(e).__name__}: {e}"
                logger.error(f"Error {msg}")
                errors.append(msg)

        # Fetch comments for each thread
        if fetch_comments:
            for thread in all_threads:
                try:
                    comments = self.fetch_thread_comments(
                        thread["subreddit"], thread["thread_id"]
                    )
                    thread["comments"] = comments
                except Exception as e:
                    logger.error(
                        f"Error fetching comments for {thread['thread_id']}: {e}"
                    )
                    thread["comments"] = []
        else:
            for thread in all_threads:
                thread["comments"] = []

        logger.info(
            f"Total: {len(all_threads)} unique threads from "
            f"{len(subreddits)} subreddits + {len(keywords)} keyword searches"
        )
        return all_threads, errors

    def close(self):
        """Close the HTTP client."""
        self.client.close()
