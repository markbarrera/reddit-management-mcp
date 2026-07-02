"""Tests for db.py, focused on the platform-aware schema and queries.

The migration regression test (test_migration_from_pre_platform_schema) is
the highest-value test in this file: it reproduces the exact production
crash found during manual testing before this suite existed (CREATE INDEX
on the platform column ran before the ALTER TABLE that added it, so
init_db() crashed against any database created before that column existed).
"""

import sqlite3

import db as db_module


def _seed_reddit_thread(db, thread_id="r1", subreddit="AmazonSeller", **overrides):
    thread = {
        "thread_id": thread_id,
        "subreddit": subreddit,
        "title": "a thread",
        "body": "body text",
        "score": 5,
        "num_comments": 1,
        "created_utc": 1_700_000_000,
        "comments": [],
    }
    thread.update(overrides)
    db.upsert_thread(thread)
    return thread


def _seed_shopify_thread(db, thread_id="sc_1", subreddit="payments-shipping-fulfilment", **overrides):
    thread = {
        "thread_id": thread_id,
        "platform": "shopify_community",
        "subreddit": subreddit,
        "title": "a shopify thread",
        "body": "body text",
        "score": 2,
        "num_comments": 0,
        "created_utc": 1_700_000_000,
        "comments": [],
    }
    thread.update(overrides)
    db.upsert_thread(thread)
    return thread


class TestMigration:
    def test_migration_from_pre_platform_schema(self, tmp_path, monkeypatch):
        """init_db() must not crash against a database created before the
        platform column existed, and must preserve existing data while
        backfilling platform='reddit'.
        """
        path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE reddit_threads (
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
                geo_signals TEXT,
                participation_status TEXT DEFAULT 'not_engaged',
                participation_priority TEXT DEFAULT 'unscored',
                participation_notes TEXT,
                embedding BLOB
            );
            CREATE TABLE scrape_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                subreddits TEXT,
                keywords TEXT,
                threads_found INTEGER DEFAULT 0,
                threads_new INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            );
            CREATE TABLE grounding_docs (
                doc_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                doc_type TEXT DEFAULT 'reference',
                content TEXT NOT NULL,
                source_url TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "INSERT INTO reddit_threads (thread_id, subreddit, title, score, "
            "num_comments, created_utc, participation_priority) "
            "VALUES ('preexisting1','AmazonSeller','a real pre-migration thread',"
            "42,7,1700000000,'high')"
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(db_module, "DB_PATH", path)
        db_module.init_db()  # must not raise

        row = db_module.get_thread("preexisting1")
        assert row is not None
        assert row["title"] == "a real pre-migration thread"
        assert row["score"] == 42
        assert row["platform"] == "reddit"

        # New data must be insertable after migration too.
        assert db_module.upsert_thread({
            "thread_id": "sc_999", "platform": "shopify_community",
            "subreddit": "accounting-taxes", "title": "new", "score": 1,
            "num_comments": 0, "created_utc": 1_800_000_000, "comments": [],
        }) is True

    def test_init_db_idempotent(self, tmp_db):
        """Running init_db() twice against the same file must not error."""
        db_module.init_db()
        db_module.init_db()


class TestUpsertThread:
    def test_defaults_platform_to_reddit(self, tmp_db):
        _seed_reddit_thread(tmp_db, thread_id="r1")
        row = tmp_db.get_thread("r1")
        assert row["platform"] == "reddit"

    def test_respects_explicit_platform(self, tmp_db):
        _seed_shopify_thread(tmp_db, thread_id="sc_1")
        row = tmp_db.get_thread("sc_1")
        assert row["platform"] == "shopify_community"

    def test_returns_true_for_new_false_for_update(self, tmp_db):
        assert tmp_db.upsert_thread({
            "thread_id": "r1", "subreddit": "AmazonSeller", "title": "t",
            "score": 1, "num_comments": 0, "created_utc": 0, "comments": [],
        }) is True
        assert tmp_db.upsert_thread({
            "thread_id": "r1", "subreddit": "AmazonSeller", "title": "t",
            "score": 2, "num_comments": 0, "created_utc": 0, "comments": [],
        }) is False


class TestPlatformScopedQueries:
    def test_search_threads_platform_filter(self, tmp_db):
        _seed_reddit_thread(tmp_db, thread_id="r1")
        _seed_shopify_thread(tmp_db, thread_id="sc_1")

        reddit_only = tmp_db.search_threads(platform="reddit")
        shopify_only = tmp_db.search_threads(platform="shopify_community")
        everything = tmp_db.search_threads()

        assert [t["thread_id"] for t in reddit_only] == ["r1"]
        assert [t["thread_id"] for t in shopify_only] == ["sc_1"]
        assert {t["thread_id"] for t in everything} == {"r1", "sc_1"}

    def test_get_stats_by_platform_breakdown(self, tmp_db):
        _seed_reddit_thread(tmp_db, thread_id="r1")
        _seed_shopify_thread(tmp_db, thread_id="sc_1")
        _seed_shopify_thread(tmp_db, thread_id="sc_2")

        stats = tmp_db.get_stats()
        by_platform = {row["platform"]: row["count"] for row in stats["by_platform"]}
        assert by_platform == {"reddit": 1, "shopify_community": 2}
        assert stats["total_threads"] == 3

    def test_get_stats_platform_filter_scopes_totals(self, tmp_db):
        _seed_reddit_thread(tmp_db, thread_id="r1")
        _seed_shopify_thread(tmp_db, thread_id="sc_1")

        stats = tmp_db.get_stats(platform="reddit")
        assert stats["total_threads"] == 1

    def test_get_stats_platform_filter_scopes_all_breakdowns(self, tmp_db):
        # Regression test: total_threads/classified used to respect the
        # platform filter while by_subreddit/by_platform/by_priority/
        # by_status silently ignored it and always aggregated across both
        # platforms — an internally inconsistent response.
        _seed_reddit_thread(tmp_db, thread_id="r1", subreddit="AmazonSeller")
        _seed_shopify_thread(tmp_db, thread_id="sc_1", subreddit="accounting-taxes")
        tmp_db.update_classification("sc_1", {"participation_priority": "high"})

        stats = tmp_db.get_stats(platform="reddit")

        assert {row["platform"] for row in stats["by_platform"]} == {"reddit"}
        assert {row["platform"] for row in stats["by_subreddit"]} == {"reddit"}
        # The Shopify thread's 'high' priority must not appear when scoped to reddit.
        priorities = {row["participation_priority"] for row in stats["by_priority"]}
        assert "high" not in priorities

    def test_get_unclassified_threads_platform_filter(self, tmp_db):
        _seed_reddit_thread(tmp_db, thread_id="r1")
        _seed_shopify_thread(tmp_db, thread_id="sc_1")

        only_shopify = tmp_db.get_unclassified_threads(batch_size=10, platform="shopify_community")
        assert [t["thread_id"] for t in only_shopify] == ["sc_1"]

    def test_get_subreddit_profile_data_scoped_by_platform(self, tmp_db):
        # Same board-name string on both platforms must not merge into
        # one profile when a platform filter is supplied.
        _seed_reddit_thread(tmp_db, thread_id="r1", subreddit="shared-name")
        _seed_shopify_thread(tmp_db, thread_id="sc_1", subreddit="shared-name")

        reddit_profile = tmp_db.get_subreddit_profile_data("shared-name", platform="reddit")
        shopify_profile = tmp_db.get_subreddit_profile_data("shared-name", platform="shopify_community")

        assert reddit_profile["total_threads_in_db"] == 1
        assert shopify_profile["total_threads_in_db"] == 1

    def test_get_subreddit_profile_data_unscoped_merges_platforms(self, tmp_db):
        # Documents current behavior: platform=None means no filter, so a
        # colliding board name across platforms merges. Callers that care
        # about platform isolation must pass platform explicitly.
        _seed_reddit_thread(tmp_db, thread_id="r1", subreddit="shared-name")
        _seed_shopify_thread(tmp_db, thread_id="sc_1", subreddit="shared-name")

        merged_profile = tmp_db.get_subreddit_profile_data("shared-name")
        assert merged_profile["total_threads_in_db"] == 2

    def test_purge_offtopic_threads_platform_scoping(self, tmp_db):
        _seed_reddit_thread(tmp_db, thread_id="r1", subreddit="keep-me")
        _seed_shopify_thread(tmp_db, thread_id="sc_1", subreddit="keep-me")
        _seed_reddit_thread(tmp_db, thread_id="r2", subreddit="off-topic")

        # Purging Reddit only must not touch the Shopify thread even though
        # neither of its board names is in keep_subreddits for this call.
        result = tmp_db.purge_offtopic_threads(
            keep_subreddits=["keep-me"], dry_run=False, platform="reddit",
        )
        assert result["deleted_count"] == 1
        assert tmp_db.get_thread("r2") is None
        assert tmp_db.get_thread("sc_1") is not None  # untouched: different platform

    def test_start_scrape_run_records_platform(self, tmp_db):
        run_id = tmp_db.start_scrape_run(["shopify-discussion"], [], platform="shopify_community")
        conn = tmp_db.get_db()
        row = conn.execute("SELECT platform FROM scrape_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["platform"] == "shopify_community"

    def test_start_scrape_run_defaults_to_reddit(self, tmp_db):
        run_id = tmp_db.start_scrape_run(["AmazonSeller"], ["financing"])
        conn = tmp_db.get_db()
        row = conn.execute("SELECT platform FROM scrape_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["platform"] == "reddit"
