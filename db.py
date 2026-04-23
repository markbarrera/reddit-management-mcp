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
            subreddits TEXT,
            keywords TEXT,
            threads_found INTEGER DEFAULT 0,
            threads_new INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );
    """)
    conn.commit()

    # Migrate: add peec.ai columns if they don't exist yet
    for col_sql in [
        "ALTER TABLE reddit_threads ADD COLUMN citation_count INTEGER DEFAULT 0",
        "ALTER TABLE reddit_threads ADD COLUMN ai_mentioned TEXT DEFAULT 'unknown'",
        "ALTER TABLE reddit_threads ADD COLUMN peec_competitors TEXT",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


# ============================================
# Thread Operations
# ============================================

def upsert_thread(thread: dict) -> bool:
    """Insert or update a Reddit thread. Returns True if new."""
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
                (thread_id, subreddit, title, body, author, url, permalink,
                 score, upvote_ratio, num_comments, created_utc,
                 comments_json, full_text, word_count,
                 citation_count, ai_mentioned, peec_competitors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            thread["thread_id"], thread["subreddit"], thread["title"],
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


def get_unclassified_threads(batch_size: int = 10) -> list[dict]:
    """Get threads that haven't been classified yet."""
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
    min_score: Optional[int] = None,
    participation_priority: Optional[str] = None,
    participation_status: Optional[str] = None,
    has_competitor: Optional[str] = None,
    time_range_days: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search threads with rich filtering."""
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
    """Get aggregate statistics."""
    conn = get_db()
    where = "WHERE subreddit = ?" if subreddit else ""
    params = (subreddit,) if subreddit else ()

    total = conn.execute(
        f"SELECT COUNT(*) FROM reddit_threads {where}", params
    ).fetchone()[0]

    classified = conn.execute(
        f"SELECT COUNT(*) FROM reddit_threads {where} {'AND' if where else 'WHERE'} classification IS NOT NULL",
        params
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

    conn.close()
    return {
        "total_threads": total,
        "classified": classified,
        "unclassified": total - classified,
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

def start_scrape_run(subreddits: list, keywords: list) -> int:
    """Record the start of a scrape run."""
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO scrape_runs (subreddits, keywords)
        VALUES (?, ?)
    """, (json.dumps(subreddits), json.dumps(keywords)))
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
