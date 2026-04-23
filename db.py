"""Database module for the Reddit Intelligence MCP.

Schema is brand-neutral. Brand-specific behavior is driven by profile.yaml.
"""

import json
import sqlite3
import logging
import os
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("REDDIT_DB_PATH", "reddit_intelligence.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema (idempotent)."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reddit_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT UNIQUE NOT NULL,
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

            comments_json TEXT DEFAULT '[]',
            full_text TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,

            classification TEXT,
            personas TEXT,
            pain_points TEXT,
            language_mining TEXT,
            signals TEXT,

            participation_status TEXT DEFAULT 'not_engaged',
            participation_priority TEXT DEFAULT 'unscored',
            participation_notes TEXT,

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
            subreddits TEXT,
            keywords TEXT,
            threads_found INTEGER DEFAULT 0,
            threads_new INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );

        -- Provider-agnostic citation tracking (peec.ai, Profound, etc.)
        CREATE TABLE IF NOT EXISTS citation_tracking (
            thread_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            citation_count INTEGER DEFAULT 0,
            brand_mentioned TEXT DEFAULT 'unknown',
            competitors_mentioned TEXT,
            raw_metadata TEXT,
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, provider),
            FOREIGN KEY (thread_id) REFERENCES reddit_threads(thread_id)
        );
        CREATE INDEX IF NOT EXISTS idx_citation_count
            ON citation_tracking(citation_count DESC);
        CREATE INDEX IF NOT EXISTS idx_citation_provider
            ON citation_tracking(provider);

        -- Feedback / learning: capture what humans actually post vs drafts
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT,
            tool_name TEXT NOT NULL,
            user_name TEXT,
            subreddit TEXT,
            thread_title TEXT,
            original_output TEXT,
            final_version TEXT,
            reason TEXT,
            outcome TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_tool ON feedback(tool_name);
        CREATE INDEX IF NOT EXISTS idx_feedback_subreddit ON feedback(subreddit);
        CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_name);
        CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
    """)
    conn.commit()

    # Legacy migration: drop peec-specific columns on reddit_threads if they
    # exist from an earlier version. We keep the data by copying into
    # citation_tracking before the column reference is abandoned.
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(reddit_threads)").fetchall()}
        if {"citation_count", "ai_mentioned", "peec_competitors"} & cols:
            rows = conn.execute(
                "SELECT thread_id, citation_count, ai_mentioned, peec_competitors "
                "FROM reddit_threads WHERE citation_count > 0 OR ai_mentioned != 'unknown'"
            ).fetchall()
            for r in rows:
                conn.execute("""
                    INSERT OR IGNORE INTO citation_tracking
                        (thread_id, provider, citation_count, brand_mentioned, competitors_mentioned)
                    VALUES (?, 'peec', ?, ?, ?)
                """, (r[0], r[1] or 0, r[2] or "unknown", r[3]))
            conn.commit()
    except sqlite3.OperationalError as e:
        logger.debug(f"Legacy migration skipped: {e}")

    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


# ============================================
# Thread Operations
# ============================================

def upsert_thread(thread: dict) -> bool:
    """Insert or update a Reddit thread. Returns True if new."""
    conn = get_db()

    parts = [thread.get("title", ""), thread.get("body", "")]
    for comment in thread.get("comments", []):
        parts.append(comment.get("body", ""))
    full_text = "\n\n".join(p for p in parts if p)
    word_count = len(full_text.split())
    comments_json = json.dumps(thread.get("comments", []))

    try:
        conn.execute("""
            INSERT INTO reddit_threads
                (thread_id, subreddit, title, body, author, url, permalink,
                 score, upvote_ratio, num_comments, created_utc,
                 comments_json, full_text, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                score = excluded.score,
                upvote_ratio = excluded.upvote_ratio,
                num_comments = excluded.num_comments,
                comments_json = excluded.comments_json,
                full_text = excluded.full_text,
                word_count = excluded.word_count,
                scraped_at = CURRENT_TIMESTAMP
        """, (
            thread["thread_id"], thread["subreddit"], thread["title"],
            thread.get("body", ""), thread.get("author", "[deleted]"),
            thread.get("url", ""), thread.get("permalink", ""),
            thread.get("score", 0), thread.get("upvote_ratio", 0.0),
            thread.get("num_comments", 0), thread.get("created_utc", 0),
            comments_json, full_text, word_count,
        ))
        is_new = conn.execute("SELECT changes()").fetchone()[0] > 0
        conn.commit()

        # Optional citation metadata (from peec.ai / Profound / etc.)
        if any(k in thread for k in ("citation_count", "brand_mentioned", "competitors_mentioned", "ai_mentioned")):
            record_citation(
                thread_id=thread["thread_id"],
                provider=thread.get("citation_provider", "unknown"),
                citation_count=thread.get("citation_count"),
                brand_mentioned=thread.get("brand_mentioned") or thread.get("ai_mentioned"),
                competitors_mentioned=thread.get("competitors_mentioned") or thread.get("peec_competitors"),
                raw_metadata=thread.get("citation_metadata"),
            )

        return is_new
    except Exception as e:
        logger.error(f"Error upserting thread {thread.get('thread_id')}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_thread(thread_id: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM reddit_threads WHERE thread_id = ?", (thread_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_unclassified_threads(batch_size: int = 10) -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM reddit_threads
        WHERE classification IS NULL
        ORDER BY score DESC, num_comments DESC
        LIMIT ?
    """, (batch_size,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_classification(thread_id: str, classification: dict):
    conn = get_db()
    conn.execute("""
        UPDATE reddit_threads SET
            classification = ?,
            personas = ?,
            pain_points = ?,
            language_mining = ?,
            signals = ?,
            participation_priority = ?
        WHERE thread_id = ?
    """, (
        json.dumps(classification),
        json.dumps(classification.get("personas", {})),
        json.dumps(classification.get("pain_points", [])),
        json.dumps(classification.get("buyer_language", [])),
        json.dumps(classification.get("signals", classification.get("geo_signals", {}))),
        classification.get("participation_priority", "unscored"),
        thread_id,
    ))
    conn.commit()
    conn.close()


def search_threads(
    query: Optional[str] = None,
    subreddit: Optional[str] = None,
    min_score: Optional[int] = None,
    participation_priority: Optional[str] = None,
    participation_status: Optional[str] = None,
    has_competitor: Optional[str] = None,
    time_range_days: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    conn = get_db()
    conditions = []
    params = []

    if query:
        conditions.append("full_text LIKE ?")
        params.append(f"%{query}%")
    if subreddit:
        conditions.append("subreddit = ?")
        params.append(subreddit)
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


def get_stats(subreddit: Optional[str] = None) -> dict:
    conn = get_db()
    where = "WHERE subreddit = ?" if subreddit else ""
    params = (subreddit,) if subreddit else ()

    total = conn.execute(f"SELECT COUNT(*) FROM reddit_threads {where}", params).fetchone()[0]
    classified = conn.execute(
        f"SELECT COUNT(*) FROM reddit_threads {where} {'AND' if where else 'WHERE'} classification IS NOT NULL",
        params,
    ).fetchone()[0]
    by_subreddit = conn.execute("""
        SELECT subreddit, COUNT(*) as count, AVG(score) as avg_score
        FROM reddit_threads GROUP BY subreddit ORDER BY count DESC
    """).fetchall()
    by_priority = conn.execute("""
        SELECT participation_priority, COUNT(*) as count
        FROM reddit_threads GROUP BY participation_priority ORDER BY count DESC
    """).fetchall()
    by_status = conn.execute("""
        SELECT participation_status, COUNT(*) as count
        FROM reddit_threads GROUP BY participation_status ORDER BY count DESC
    """).fetchall()
    feedback_count = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    conn.close()
    return {
        "total_threads": total,
        "classified": classified,
        "unclassified": total - classified,
        "by_subreddit": [dict(r) for r in by_subreddit],
        "by_priority": [dict(r) for r in by_priority],
        "by_status": [dict(r) for r in by_status],
        "feedback_entries": feedback_count,
    }


# ============================================
# Grounding Document Operations
# ============================================

def store_grounding_doc(doc_key: str, title: str, content: str,
                        doc_type: str = "reference", source_url: str = None):
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
    conn = get_db()
    row = conn.execute(
        "SELECT content FROM grounding_docs WHERE doc_key = ?", (doc_key,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def list_grounding_docs() -> list[dict]:
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

def start_scrape_run(subreddits: list, keywords: list) -> int:
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO scrape_runs (subreddits, keywords) VALUES (?, ?)",
        (json.dumps(subreddits), json.dumps(keywords)),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def complete_scrape_run(run_id: int, threads_found: int, threads_new: int):
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


# ============================================
# Citation Tracker (peec.ai / Profound / etc.)
# ============================================

def record_citation(
    thread_id: str,
    provider: str,
    citation_count: Optional[int] = None,
    brand_mentioned: Optional[str] = None,
    competitors_mentioned=None,
    raw_metadata: Optional[dict] = None,
):
    """Record a citation data point for a thread from a tracking provider."""
    if isinstance(competitors_mentioned, list):
        competitors_mentioned = json.dumps(competitors_mentioned)
    conn = get_db()
    conn.execute("""
        INSERT INTO citation_tracking
            (thread_id, provider, citation_count, brand_mentioned, competitors_mentioned, raw_metadata)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(thread_id, provider) DO UPDATE SET
            citation_count = excluded.citation_count,
            brand_mentioned = excluded.brand_mentioned,
            competitors_mentioned = excluded.competitors_mentioned,
            raw_metadata = excluded.raw_metadata,
            imported_at = CURRENT_TIMESTAMP
    """, (
        thread_id, provider,
        citation_count or 0,
        brand_mentioned or "unknown",
        competitors_mentioned,
        json.dumps(raw_metadata) if raw_metadata else None,
    ))
    conn.commit()
    conn.close()


def get_citation_gaps(provider: Optional[str] = None, min_count: int = 30, limit: int = 50) -> list[dict]:
    """Find threads where the brand is NOT cited but competitors are,
    with high AI citation counts (a high-leverage content gap)."""
    conn = get_db()
    where = "WHERE c.brand_mentioned IN ('No', 'no', '0', 'false') AND c.citation_count >= ?"
    params: list = [min_count]
    if provider:
        where += " AND c.provider = ?"
        params.append(provider)
    rows = conn.execute(f"""
        SELECT t.thread_id, t.subreddit, t.title, t.url,
               c.citation_count, c.brand_mentioned, c.competitors_mentioned, c.provider
        FROM citation_tracking c
        JOIN reddit_threads t ON t.thread_id = c.thread_id
        {where}
        ORDER BY c.citation_count DESC
        LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================
# Feedback / Learning
# ============================================

def log_feedback(
    tool_name: str,
    original_output: str,
    final_version: str,
    reason: str,
    thread_id: Optional[str] = None,
    subreddit: Optional[str] = None,
    thread_title: Optional[str] = None,
    user_name: Optional[str] = None,
    outcome: Optional[str] = None,
) -> int:
    """Record a human edit for learning. Returns the feedback id."""
    if thread_id and not (subreddit and thread_title):
        row = get_thread(thread_id)
        if row:
            subreddit = subreddit or row.get("subreddit")
            thread_title = thread_title or row.get("title")
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO feedback
            (thread_id, tool_name, user_name, subreddit, thread_title,
             original_output, final_version, reason, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        thread_id, tool_name, user_name, subreddit, thread_title,
        original_output, final_version, reason, outcome,
    ))
    feedback_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return feedback_id


def get_relevant_feedback(
    tool_name: Optional[str] = None,
    subreddit: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Retrieve recent feedback for few-shot prompt injection.

    Prefers feedback from the same subreddit, then same tool, then most recent.
    Each record is shaped for the prompt template: original_text / final_text / reason.
    """
    conn = get_db()
    conditions = []
    params: list = []
    if tool_name:
        conditions.append("tool_name = ?")
        params.append(tool_name)

    base_query = f"""
        SELECT thread_id, subreddit, thread_title, original_output AS original_text,
               final_version AS final_text, reason, outcome, user_name, created_at
        FROM feedback
        {'WHERE ' + ' AND '.join(conditions) if conditions else ''}
        ORDER BY
          CASE WHEN subreddit = ? THEN 0 ELSE 1 END,
          created_at DESC
        LIMIT ?
    """
    rows = conn.execute(base_query, params + [subreddit or "", limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_feedback_history(
    tool_name: Optional[str] = None,
    user_name: Optional[str] = None,
    subreddit: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    conn = get_db()
    conditions = []
    params: list = []
    if tool_name:
        conditions.append("tool_name = ?")
        params.append(tool_name)
    if user_name:
        conditions.append("user_name = ?")
        params.append(user_name)
    if subreddit:
        conditions.append("subreddit = ?")
        params.append(subreddit)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(f"""
        SELECT id, thread_id, tool_name, user_name, subreddit, thread_title,
               original_output, final_version, reason, outcome, created_at
        FROM feedback
        {where}
        ORDER BY created_at DESC
        LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Initialize on import
init_db()
