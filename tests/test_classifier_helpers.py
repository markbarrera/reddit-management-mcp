"""Tests for classifier.py's platform-aware helper functions."""

from classifier import _community_label, _platform_noun, _engagement_rules_doc_key


class TestCommunityLabel:
    def test_reddit_thread(self):
        assert _community_label({"platform": "reddit", "subreddit": "AmazonSeller"}) == "Subreddit: r/AmazonSeller"

    def test_shopify_thread(self):
        assert _community_label({"platform": "shopify_community", "subreddit": "accounting-taxes"}) == \
            "Shopify Community board: accounting-taxes"

    def test_missing_platform_defaults_to_reddit(self):
        # A thread dict without a platform key (e.g. hand-built in a test
        # or an older code path) must not crash and must read as Reddit.
        assert _community_label({"subreddit": "ecommerce"}) == "Subreddit: r/ecommerce"

    def test_missing_subreddit_falls_back_to_unknown(self):
        assert "unknown" in _community_label({"platform": "reddit"})


class TestPlatformNoun:
    def test_reddit(self):
        assert _platform_noun({"platform": "reddit"}) == "Reddit"

    def test_shopify(self):
        assert _platform_noun({"platform": "shopify_community"}) == "Shopify Community"

    def test_missing_platform_defaults_to_reddit(self):
        assert _platform_noun({}) == "Reddit"

    def test_unknown_platform_value_defaults_to_reddit(self):
        # Only shopify_community is special-cased; anything else (including
        # a typo'd platform value) must fail safe to Reddit's rules rather
        # than silently produce blank/incorrect grounding.
        assert _platform_noun({"platform": "some_future_platform"}) == "Reddit"


class TestEngagementRulesDocKey:
    def test_reddit(self):
        assert _engagement_rules_doc_key({"platform": "reddit"}) == "reddit_engagement_rules"

    def test_shopify(self):
        assert _engagement_rules_doc_key({"platform": "shopify_community"}) == "shopify_community_engagement_rules"

    def test_missing_platform_defaults_to_reddit_rules(self):
        assert _engagement_rules_doc_key({}) == "reddit_engagement_rules"
