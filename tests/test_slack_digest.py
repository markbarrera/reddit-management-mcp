"""Tests for slack_digest.py: platform labeling and the per-platform
classification split (regression test for Shopify Community threads being
starved out of classification by Reddit's larger score scale).
"""

import slack_digest as sd


class TestCommunityLabel:
    def test_reddit_thread(self):
        assert sd._community_label({"platform": "reddit", "subreddit": "AmazonSeller"}) == "r/AmazonSeller"

    def test_shopify_thread(self):
        assert sd._community_label({"platform": "shopify_community", "subreddit": "accounting-taxes"}) == \
            "Shopify Community: accounting-taxes"

    def test_missing_platform_defaults_to_reddit_label(self):
        assert sd._community_label({"subreddit": "ecommerce"}) == "r/ecommerce"


class TestFormatThreadBlock:
    def test_uses_platform_aware_label(self):
        block = sd._format_thread_block({
            "platform": "shopify_community", "subreddit": "accounting-taxes",
            "title": "t", "url": "https://x", "score": 3, "num_comments": 1,
            "participation_priority": "high", "classification": "{}",
        })
        text = block["text"]["text"]
        assert "Shopify Community: accounting-taxes" in text
        assert "r/accounting-taxes" not in text


class TestMainClassificationSplit:
    def test_classifies_each_platform_separately(self, mocker, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/test")
        monkeypatch.setenv("REDDIT_DIGEST_INGEST", "0")
        monkeypatch.setenv("SHOPIFY_DIGEST_INGEST", "0")
        monkeypatch.setenv("REDDIT_DIGEST_CLASSIFY", "1")
        monkeypatch.setenv("DIGEST_CLASSIFY_BATCH_SIZE", "10")

        mock_classify = mocker.patch.object(sd, "classify_batch", return_value={"classified": 0})
        mocker.patch.object(sd, "_recent_priority_threads", return_value=[])
        mocker.patch.object(sd, "post_to_slack")

        sd.main()

        # Regression: a single classify_batch(batch_size=N) call with no
        # platform filter lets Reddit's larger score scale crowd out
        # Shopify Community threads entirely. Must be two scoped calls.
        calls = mock_classify.call_args_list
        assert len(calls) == 2
        platforms_called = {c.kwargs.get("platform") for c in calls}
        assert platforms_called == {"reddit", "shopify_community"}

        # Budget split must not silently drop or double-count the total.
        total_requested = sum(c.kwargs.get("batch_size", 0) for c in calls)
        assert total_requested == 10

    def test_skips_classification_when_disabled(self, mocker, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/test")
        monkeypatch.setenv("REDDIT_DIGEST_INGEST", "0")
        monkeypatch.setenv("SHOPIFY_DIGEST_INGEST", "0")
        monkeypatch.setenv("REDDIT_DIGEST_CLASSIFY", "0")

        mock_classify = mocker.patch.object(sd, "classify_batch")
        mocker.patch.object(sd, "_recent_priority_threads", return_value=[])
        mocker.patch.object(sd, "post_to_slack")

        sd.main()

        mock_classify.assert_not_called()
