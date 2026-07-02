"""Database module for Reddit Intelligence MCP."""

import json
import sqlite3
import logging
import os
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("REDDIT_DB_PATH", "reddit_intelligence.db")


def get_db() -> sqlite3.Connection:
    """Get a database connection."""
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reddit_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT UNIQUE NOT NULL,
            platform TEXT NOT NULL DEFAULT 'reddit',
            subreddit TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT DEFAULT '',
            author TEXT DEFAULT '[deleted]',
            url TEXT,
            permalink TEXT,
            score INTEGER DEFAULT 0,
            upvote_ratio REAL DEFAULT 0.0,
            num_comments INTEGER DEFAULT 0,
            created_utc REAL DEFAULT 0,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            -- Full comment tree as JSON
            comments_json TEXT DEFAULT '[]',

            -- Combined searchable text
            full_text TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,

            -- Classification (populated by classifier)
            classification TEXT,
            personas TEXT,
            pain_points TEXT,
            language_mining TEXT,
            geo_signals TEXT,

            -- Action tracking
            participation_status TEXT DEFAULT 'not_engaged',
            participation_priority TEXT DEFAULT 'unscored',
            participation_notes TEXT,

            -- Embedding for vector search
            embedding BLOB
        );

        CREATE INDEX IF NOT EXISTS idx_reddit_thread_id ON reddit_threads(thread_id);
        CREATE INDEX IF NOT EXISTS idx_reddit_subreddit ON reddit_threads(subreddit);
        CREATE INDEX IF NOT EXISTS idx_reddit_score ON reddit_threads(score DESC);
        CREATE INDEX IF NOT EXISTS idx_reddit_created ON reddit_threads(created_utc DESC);
        CREATE INDEX IF NOT EXISTS idx_reddit_priority ON reddit_threads(participation_priority);
        CREATE INDEX IF NOT EXISTS idx_reddit_status ON reddit_threads(participation_status);
        CREATE INDEX IF NOT EXISTS idx_reddit_scraped ON reddit_threads(scraped_at DESC);

        CREATE TABLE IF NOT EXISTS grounding_docs (
            doc_key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            doc_type TEXT DEFAULT 'reference',
            content TEXT NOT NULL,
            source_url TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            platform TEXT NOT NULL DEFAULT 'reddit',
            subreddits TEXT,
            keywords TEXT,
            threads_found INTEGER DEFAULT 0,
            threads_new INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );
    """)
    conn.commit()

    # Migrate: add columns that postdate the original schema, if they
    # don't exist yet. Existing rows default to 'reddit' so this MCP's
    # original (Reddit-only) data keeps working unmodified.
    for col_sql in [
        "ALTER TABLE reddit_threads ADD COLUMN citation_count INTEGER DEFAULT 0",
        "ALTER TABLE reddit_threads ADD COLUMN ai_mentioned TEXT DEFAULT 'unknown'",
        "ALTER TABLE reddit_threads ADD COLUMN peec_competitors TEXT",
        "ALTER TABLE reddit_threads ADD COLUMN platform TEXT NOT NULL DEFAULT 'reddit'",
        "ALTER TABLE scrape_runs ADD COLUMN platform TEXT NOT NULL DEFAULT 'reddit'",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # This index must be created after the migration above, not in the
    # initial executescript: on a database that predates the platform
    # column, reddit_threads already exists (CREATE TABLE IF NOT EXISTS is
    # a no-op) and doesn't have the column yet, so indexing it any earlier
    # fails with "no such column: platform".
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reddit_platform ON reddit_threads(platform)")
    conn.commit()

    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


# ============================================
# Thread Operations
# ============================================

def upsert_thread(thread: dict) -> bool:
    """Insert or update a community thread. Returns True if new.

    thread["platform"] defaults to "reddit" if absent, so existing
    Reddit-only callers are unaffected.
    """
    conn = get_db()

    # Build full_text from title + body + comments
    parts = [thread.get("title", ""), thread.get("body", "")]
    for comment in thread.get("comments", []):
        parts.append(comment.get("body", ""))
    full_text = "\n\n".join(p for p in parts if p)
    word_count = len(full_text.split())

    comments_json = json.dumps(thread.get("comments", []))

    citation_count = thread.get("citation_count")
    ai_mentioned = thread.get("ai_mentioned")
    peec_competitors = thread.get("peec_competitors")
    if isinstance(peec_competitors, list):
        peec_competitors = json.dumps(peec_competitors)

    # Build dynamic SET clause for peec.ai fields when present
    peec_update = ""
    if citation_count is not None:
        peec_update += ", citation_count = excluded.citation_count"
    if ai_mentioned is not None:
        peec_update += ", ai_mentioned = excluded.ai_mentioned"
    if peec_competitors is not None:
        peec_update += ", peec_competitors = excluded.peec_competitors"

    try:
        conn.execute(f"""
            INSERT INTO reddit_threads
                (thread_id, platform, subreddit, title, body, author, url, permalink,
                 score, upvote_ratio, num_comments, created_utc,
                 comments_json, full_text, word_count,
                 citation_count, ai_mentioned, peec_competitors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                score = excluded.score,
                upvote_ratio = excluded.upvote_ratio,
                num_comments = excluded.num_comments,
                comments_json = excluded.comments_json,
                full_text = excluded.full_text,
                word_count = excluded.word_count,
                scraped_at = CURRENT_TIMESTAMP
                {peec_update}
        """, (
            thread["thread_id"], thread.get("platform", "reddit"),
            thread["subreddit"], thread["title"],
            thread.get("body", ""), thread.get("author", "[deleted]"),
            thread.get("url", ""), thread.get("permalink", ""),
            thread.get("score", 0), thread.get("upvote_ratio", 0.0),
            thread.get("num_comments", 0), thread.get("created_utc", 0),
            comments_json, full_text, word_count,
            citation_count or 0, ai_mentioned or "unknown", peec_competitors,
        ))
        is_new = conn.execute(
            "SELECT changes()"
        ).fetchone()[0] > 0
        conn.commit()
        return is_new
    except Exception as e:
        logger.error(f"Error upserting thread {thread.get('thread_id')}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_thread(thread_id: str) -> Optional[dict]:
    """Get a thread by its Reddit ID."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reddit_threads WHERE thread_id = ?", (thread_id,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_unclassified_threads(batch_size: int = 10, platform: Optional[str] = None) -> list[dict]:
    """Get threads that haven't been classified yet.

    platform: Restrict to this platform ("reddit", "shopify_community").
        Omit to pull from all platforms (note: score scales differ between
        platforms, so ORDER BY score mixes them by raw magnitude).
    """
    conn = get_db()
    if platform:
        rows = conn.execute("""
            SELECT * FROM reddit_threads
            WHERE classification IS NULL AND platform = ?
            ORDER BY score DESC, num_comments DESC
            LIMIT ?
        """, (platform, batch_size)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM reddit_threads
            WHERE classification IS NULL
            ORDER BY score DESC, num_comments DESC
            LIMIT ?
        """, (batch_size,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_classification(thread_id: str, classification: dict):
    """Store classification results for a thread."""
    conn = get_db()
    conn.execute("""
        UPDATE reddit_threads SET
            classification = ?,
            personas = ?,
            pain_points = ?,
            language_mining = ?,
            geo_signals = ?,
            participation_priority = ?
        WHERE thread_id = ?
    """, (
        json.dumps(classification),
        json.dumps(classification.get("personas", {})),
        json.dumps(classification.get("pain_points", [])),
        json.dumps(classification.get("buyer_language", [])),
        json.dumps(classification.get("geo_signals", {})),
        classification.get("participation_priority", "unscored"),
        thread_id,
    ))
    conn.commit()
    conn.close()


def search_threads(
    query: Optional[str] = None,
    subreddit: Optional[str] = None,
    platform: Optional[str] = None,
    min_score: Optional[int] = None,
    participation_priority: Optional[str] = None,
    participation_status: Optional[str] = None,
    has_competitor: Optional[str] = None,
    time_range_days: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search threads with rich filtering.

    platform: Filter by source platform ("reddit", "shopify_community").
        Omit to search across all platforms.
    """
    conn = get_db()
    conditions = []
    params = []

    if query:
        conditions.append("full_text LIKE ?")
        params.append(f"%{query}%")
    if subreddit:
        conditions.append("subreddit = ?")
        params.append(subreddit)
    if platform:
        conditions.append("platform = ?")
        params.append(platform)
    if min_score is not None:
        conditions.append("score >= ?")
        params.append(min_score)
    if participation_priority:
        conditions.append("participation_priority = ?")
        params.append(participation_priority)
    if participation_status:
        conditions.append("participation_status = ?")
        params.append(participation_status)
    if has_competitor:
        conditions.append("classification LIKE ?")
        params.append(f'%"{has_competitor}"%')
    if time_range_days:
        import time as _time
        cutoff = _time.time() - (time_range_days * 86400)
        conditions.append("created_utc >= ?")
        params.append(cutoff)

    where = " AND ".join(conditions) if conditions else "1=1"
    params.extend([limit, offset])

    rows = conn.execute(f"""
        SELECT * FROM reddit_threads
        WHERE {where}
        ORDER BY score DESC, created_utc DESC
        LIMIT ? OFFSET ?
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purge_offtopic_threads(
    keep_subreddits: list[str],
    protect_priorities: Optional[list[str]] = None,
    dry_run: bool = True,
    platform: Optional[str] = None,
) -> dict:
    """Delete threads whose subreddit is not in keep_subreddits.

    Used to clean up off-topic noise from broad keyword searches that
    happened to surface threads from unrelated subreddits.

    Args:
        keep_subreddits: Subreddit/board names to keep (case-insensitive match)
        protect_priorities: Never delete threads with these participation
            priorities. Defaults to ['urgent', 'high'] so any human-curated
            high-value thread survives even if it's in an off-topic sub.
        dry_run: If True (default), only report what would be deleted.
            Set False to actually delete.
        platform: Only consider threads from this platform ("reddit",
            "shopify_community"). Omit to consider all platforms — only
            safe when keep_subreddits names can't collide across platforms.

    Returns:
        Summary dict with counts and a per-subreddit breakdown of what
        was (or would be) deleted.
    """
    if protect_priorities is None:
        protect_priorities = ["urgent", "high"]

    keep_lower = {s.lower().lstrip("r/").strip() for s in keep_subreddits}
    conn = get_db()

    # Find candidates for deletion
    if platform:
        rows = conn.execute("""
            SELECT thread_id, subreddit, title, participation_priority
            FROM reddit_threads WHERE platform = ?
        """, (platform,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT thread_id, subreddit, title, participation_priority
            FROM reddit_threads
        """).fetchall()

    to_delete = []
    protected = []
    for r in rows:
        sub_lower = (r["subreddit"] or "").lower()
        if sub_lower in keep_lower:
            continue
        if r["participation_priority"] in protect_priorities:
            protected.append(dict(r))
            continue
        to_delete.append(dict(r))

    # Group counts by subreddit
    by_sub = {}
    for t in to_delete:
        sub = t["subreddit"] or "(unknown)"
        by_sub[sub] = by_sub.get(sub, 0) + 1
    by_sub_sorted = sorted(by_sub.items(), key=lambda kv: -kv[1])

    if not dry_run and to_delete:
        ids = [t["thread_id"] for t in to_delete]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM reddit_threads WHERE thread_id IN ({placeholders})",
            ids,
        )
        conn.commit()

    total_remaining = conn.execute(
        "SELECT COUNT(*) FROM reddit_threads"
    ).fetchone()[0]
    conn.close()

    return {
        "dry_run": dry_run,
        "deleted_count": len(to_delete) if not dry_run else 0,
        "would_delete_count": len(to_delete) if dry_run else 0,
        "protected_count": len(protected),
        "remaining_threads": total_remaining,
        "by_subreddit": [
            {"subreddit": s, "count": c} for s, c in by_sub_sorted[:30]
        ],
        "sample_titles": [
            {"subreddit": t["subreddit"], "title": (t["title"] or "")[:90]}
            for t in to_delete[:10]
        ],
        "protected_sample": [
            {
                "subreddit": t["subreddit"],
                "title": (t["title"] or "")[:90],
                "priority": t["participation_priority"],
            }
            for t in protected[:5]
        ],
    }


def get_subreddit_profile_data(subreddit: str, platform: Optional[str] = None) -> dict:
    """Aggregate DB stats for one subreddit/board into a profile.

    Returns thread counts, score stats, topic distribution, persona mix,
    competitor mentions with sentiment, top-scoring threads, and a sample
    of low-scoring threads that included vendor language (for "what
    doesn't work here" signal).

    Args:
        subreddit: Subreddit/board name (case-insensitive, "r/" prefix stripped)
        platform: Restrict to this platform ("reddit", "shopify_community").
            Omit only if you're sure the name can't collide across platforms.

    Returns:
        Dict with the profile. If no threads exist in DB for the sub,
        returns a stub with total_threads=0.
    """
    sub_lower = (subreddit or "").lower().lstrip("r/").strip()
    if not sub_lower:
        return {"subreddit": subreddit, "total_threads_in_db": 0,
                "message": "Empty subreddit name"}

    conn = get_db()
    plat_clause = " AND platform = ?" if platform else ""
    plat_params = (platform,) if platform else ()

    row = conn.execute(f"""
        SELECT
            COUNT(*) as total,
            AVG(score) as avg_score,
            AVG(num_comments) as avg_comments,
            MIN(created_utc) as oldest,
            MAX(created_utc) as newest
        FROM reddit_threads
        WHERE LOWER(subreddit) = ?{plat_clause}
    """, (sub_lower, *plat_params)).fetchone()

    total = row["total"] or 0
    if total == 0:
        conn.close()
        return {
            "subreddit": subreddit,
            "total_threads_in_db": 0,
            "message": "No threads from this subreddit in our DB yet. "
                       "Run reddit_ingest with this subreddit before "
                       "building a profile.",
        }

    topic_counts: dict = {}
    persona_counts: dict = {}
    competitor_mentions: dict = {}
    classified_count = 0

    rows = conn.execute(f"""
        SELECT classification
        FROM reddit_threads
        WHERE LOWER(subreddit) = ?{plat_clause} AND classification IS NOT NULL
    """, (sub_lower, *plat_params)).fetchall()

    for r in rows:
        try:
            cls = json.loads(r["classification"])
        except (json.JSONDecodeError, TypeError):
            continue
        classified_count += 1
        topic = cls.get("topic")
        if topic:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        persona = (cls.get("personas") or {}).get("thread_author")
        if persona:
            persona_counts[persona] = persona_counts.get(persona, 0) + 1
        for c in (cls.get("entities") or {}).get("competitors", []) or []:
            name = c.get("name")
            sent = c.get("sentiment", "neutral")
            if not name:
                continue
            entry = competitor_mentions.setdefault(
                name, {"count": 0, "sentiments": []}
            )
            entry["count"] += 1
            entry["sentiments"].append(sent)

    top_rows = conn.execute(f"""
        SELECT thread_id, title, score, num_comments,
               participation_priority, url
        FROM reddit_threads
        WHERE LOWER(subreddit) = ?{plat_clause}
        ORDER BY score DESC
        LIMIT 5
    """, (sub_lower, *plat_params)).fetchall()

    bottom_rows = conn.execute(f"""
        SELECT thread_id, title, score, num_comments,
               participation_priority, url, classification
        FROM reddit_threads
        WHERE LOWER(subreddit) = ?{plat_clause}
        ORDER BY score ASC
        LIMIT 5
    """, (sub_lower, *plat_params)).fetchall()

    conn.close()

    return {
        "subreddit": subreddit,
        "total_threads_in_db": total,
        "classified_threads": classified_count,
        "avg_score": round(row["avg_score"] or 0, 1),
        "avg_comments": round(row["avg_comments"] or 0, 1),
        "topic_distribution": sorted(
            topic_counts.items(), key=lambda x: -x[1]
        ),
        "persona_distribution": sorted(
            persona_counts.items(), key=lambda x: -x[1]
        ),
        "competitor_mentions": {
            name: {
                "count": data["count"],
                "sentiment_breakdown": {
                    s: data["sentiments"].count(s)
                    for s in sorted(set(data["sentiments"]))
                },
            }
            for name, data in sorted(
                competitor_mentions.items(), key=lambda x: -x[1]["count"]
            )[:10]
        },
        "top_threads": [
            {
                "thread_id": r["thread_id"],
                "title": (r["title"] or "")[:120],
                "score": r["score"],
                "num_comments": r["num_comments"],
                "priority": r["participation_priority"],
                "url": r["url"],
            }
            for r in top_rows
        ],
        "low_score_sample": [
            {
                "thread_id": r["thread_id"],
                "title": (r["title"] or "")[:120],
                "score": r["score"],
                "num_comments": r["num_comments"],
                "priority": r["participation_priority"],
                "url": r["url"],
            }
            for r in bottom_rows
        ],
    }


def get_stats(subreddit: Optional[str] = None, platform: Optional[str] = None) -> dict:
    """Get aggregate statistics.

    platform: Restrict to this platform ("reddit", "shopify_community").
        Omit to aggregate across all platforms.
    """
    conn = get_db()
    conditions = []
    params: list = []
    if subreddit:
        conditions.append("subreddit = ?")
        params.append(subreddit)
    if platform:
        conditions.append("platform = ?")
        params.append(platform)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM reddit_threads {where}", params
    ).fetchone()[0]

    classified = conn.execute(
        f"SELECT COUNT(*) FROM reddit_threads {where} {'AND' if where else 'WHERE'} classification IS NOT NULL",
        params
    ).fetchone()[0]

    by_subreddit = conn.execute("""
        SELECT platform, subreddit, COUNT(*) as count, AVG(score) as avg_score
        FROM reddit_threads GROUP BY platform, subreddit ORDER BY count DESC
    """).fetchall()

    by_platform = conn.execute("""
        SELECT platform, COUNT(*) as count
        FROM reddit_threads GROUP BY platform ORDER BY count DESC
    """).fetchall()

    by_priority = conn.execute("""
        SELECT participation_priority, COUNT(*) as count
        FROM reddit_threads GROUP BY participation_priority ORDER BY count DESC
    """).fetchall()

    by_status = conn.execute("""
        SELECT participation_status, COUNT(*) as count
        FROM reddit_threads GROUP BY participation_status ORDER BY count DESC
    """).fetchall()

    conn.close()
    return {
        "total_threads": total,
        "classified": classified,
        "unclassified": total - classified,
        "by_platform": [dict(r) for r in by_platform],
        "by_subreddit": [dict(r) for r in by_subreddit],
        "by_priority": [dict(r) for r in by_priority],
        "by_status": [dict(r) for r in by_status],
    }


# ============================================
# Grounding Document Operations
# ============================================

def store_grounding_doc(doc_key: str, title: str, content: str,
                        doc_type: str = "reference", source_url: str = None):
    """Store or update a grounding document."""
    conn = get_db()
    conn.execute("""
        INSERT INTO grounding_docs (doc_key, title, doc_type, content, source_url, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(doc_key) DO UPDATE SET
            title = excluded.title,
            doc_type = excluded.doc_type,
            content = excluded.content,
            source_url = excluded.source_url,
            updated_at = CURRENT_TIMESTAMP
    """, (doc_key, title, doc_type, content, source_url))
    conn.commit()
    conn.close()


def get_grounding_doc(doc_key: str) -> Optional[str]:
    """Retrieve a grounding document's content by key."""
    conn = get_db()
    row = conn.execute(
        "SELECT content FROM grounding_docs WHERE doc_key = ?", (doc_key,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def list_grounding_docs() -> list[dict]:
    """List all grounding documents."""
    conn = get_db()
    rows = conn.execute("""
        SELECT doc_key, title, doc_type, LENGTH(content) as size, updated_at
        FROM grounding_docs ORDER BY doc_key
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================
# Scrape Run Tracking
# ============================================

def start_scrape_run(subreddits: list, keywords: list, platform: str = "reddit") -> int:
    """Record the start of a scrape run."""
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO scrape_runs (platform, subreddits, keywords)
        VALUES (?, ?, ?)
    """, (platform, json.dumps(subreddits), json.dumps(keywords)))
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def complete_scrape_run(run_id: int, threads_found: int, threads_new: int):
    """Record the completion of a scrape run."""
    conn = get_db()
    conn.execute("""
        UPDATE scrape_runs SET
            completed_at = CURRENT_TIMESTAMP,
            threads_found = ?,
            threads_new = ?,
            status = 'completed'
        WHERE id = ?
    """, (threads_found, threads_new, run_id))
    conn.commit()
    conn.close()


# Initialize on import
init_db()
