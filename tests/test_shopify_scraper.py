"""Tests for shopify_scraper.py. Network calls are mocked — CI must not
depend on community.shopify.com being reachable or unchanged.
"""

import pytest

from shopify_scraper import ShopifyCommunityScraper, _CookedTextExtractor, DEFAULT_CATEGORIES


class TestCookedTextExtractor:
    """_strip_html / _CookedTextExtractor: the fix for the real bug found
    in manual testing, where Discourse's image-caption markup ("550x342
    21.2 KB") and quoted-reply blocks bled into plain text as if they were
    the author's own words.
    """

    def test_plain_paragraphs(self):
        html = "<p>Hello there.</p><p>Second paragraph.</p>"
        text = ShopifyCommunityScraper._strip_html(html)
        assert "Hello there." in text
        assert "Second paragraph." in text

    def test_image_caption_does_not_leak(self):
        # Real markup captured from community.shopify.com/t/.../35206
        html = (
            '<p>before text</p>'
            '<p><div class="lightbox-wrapper">'
            '<a class="lightbox" href="https://cdn.example/x.png" title="21-02-f83tx-1gf0s" rel="noopener nofollow ugc">'
            '<img src="https://cdn.example/x.png" alt="21-02-f83tx-1gf0s" width="550" height="342">'
            '<div class="meta">'
            '<svg class="fa d-icon d-icon-far-image svg-icon"><use href="#far-image"></use></svg>'
            '<span class="filename">21-02-f83tx-1gf0s</span>'
            '<span class="informations">550×342 21.2 KB</span>'
            '<svg class="fa d-icon d-icon-discourse-expand svg-icon"><use href="#discourse-expand"></use></svg>'
            '</div></a></div></p>'
            '<p>after text</p>'
        )
        text = ShopifyCommunityScraper._strip_html(html)
        assert "before text" in text
        assert "after text" in text
        assert "[image]" in text
        assert "550" not in text  # dimensions/size caption must not leak
        assert "21.2 KB" not in text
        assert "f83tx" not in text  # filename must not leak

    def test_quote_block_dropped_not_merged(self):
        html = (
            '<aside class="quote" data-username="OP" data-post="1" data-topic="123">'
            '<div class="title">OP:</div>'
            "<blockquote><p>This is the original poster's quoted text.</p></blockquote>"
            "</aside>"
            "<p>Here is my actual reply text.</p>"
        )
        text = ShopifyCommunityScraper._strip_html(html)
        assert "quoted text" not in text
        assert "Here is my actual reply text." in text

    def test_nested_divs_inside_lightbox_do_not_break_skip_depth(self):
        # The .meta div nests inside .lightbox-wrapper, both are <div>.
        # Skip-depth tracking must not exit early on the inner div's close.
        html = (
            '<div class="lightbox-wrapper">'
            '<div class="outer-nested"><div class="inner-nested">junk</div></div>'
            "</div>"
            "<p>real content after</p>"
        )
        text = ShopifyCommunityScraper._strip_html(html)
        assert "junk" not in text
        assert "real content after" in text

    def test_empty_input(self):
        assert ShopifyCommunityScraper._strip_html("") == ""
        assert ShopifyCommunityScraper._strip_html(None) == ""

    def test_html_entities_unescaped(self):
        html = "<p>Sellers &amp; sourcing &mdash; it&#39;s complicated</p>"
        text = ShopifyCommunityScraper._strip_html(html)
        assert "&amp;" not in text
        assert "Sellers & sourcing" in text


class TestFetchTopicByUrl:
    def test_parses_standard_topic_url(self, mocker):
        scraper = ShopifyCommunityScraper()
        mock_response = {
            "title": "Test Topic",
            "category_id": 217,
            "like_count": 3,
            "reply_count": 1,
            "created_at": "2024-01-01T00:00:00.000Z",
            "post_stream": {
                "posts": [
                    {"username": "op_user", "cooked": "<p>original post</p>", "created_at": "2024-01-01T00:00:00.000Z"},
                    {"username": "replier", "cooked": "<p>a reply</p>", "score": 1.0, "created_at": "2024-01-02T00:00:00.000Z"},
                ]
            },
        }
        mocker.patch.object(scraper, "_request", return_value=mock_response)
        thread = scraper.fetch_topic_by_url(
            "https://community.shopify.com/t/test-topic/12345"
        )
        assert thread is not None
        assert thread["thread_id"] == "sc_12345"
        assert thread["platform"] == "shopify_community"
        assert thread["subreddit"] == "payments-shipping-fulfilment"  # resolved from category_id 217
        assert thread["body"] == "original post"
        assert len(thread["comments"]) == 1
        assert thread["comments"][0]["author"] == "replier"

    def test_unresolvable_category_gets_synthetic_label(self, mocker):
        scraper = ShopifyCommunityScraper()
        mock_response = {
            "title": "Test",
            "category_id": 999999,  # not in DEFAULT_CATEGORIES
            "like_count": 0,
            "reply_count": 0,
            "created_at": "2024-01-01T00:00:00.000Z",
            "post_stream": {"posts": [{"username": "u", "cooked": "<p>x</p>", "created_at": "2024-01-01T00:00:00.000Z"}]},
        }
        mocker.patch.object(scraper, "_request", return_value=mock_response)
        thread = scraper.fetch_topic_by_url("https://community.shopify.com/t/test/999")
        assert thread["subreddit"] == "category_999999"

    def test_malformed_url_returns_none(self):
        scraper = ShopifyCommunityScraper()
        assert scraper.fetch_topic_by_url("https://community.shopify.com/not-a-topic-url") is None

    def test_empty_response_returns_none(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={})
        assert scraper.fetch_topic_by_url("https://community.shopify.com/t/x/1") is None

    def test_no_posts_in_stream_returns_none(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={
            "title": "t", "category_id": 217, "post_stream": {"posts": []},
        })
        assert scraper.fetch_topic_by_url("https://community.shopify.com/t/x/1") is None


class TestScrapeCategory:
    def test_single_page_no_more_topics_url(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={
            "topic_list": {
                "topics": [
                    {"id": 1, "title": "First", "slug": "first", "like_count": 5, "reply_count": 2, "created_at": "2024-01-01T00:00:00.000Z"},
                    {"id": 2, "title": "Second", "slug": "second", "like_count": 1, "reply_count": 0, "created_at": "2024-01-02T00:00:00.000Z"},
                ],
                # no more_topics_url -> single page
            }
        })
        threads = scraper.scrape_category("shopify-discussion", 95, limit=10)
        assert len(threads) == 2
        assert threads[0]["thread_id"] == "sc_1"
        assert threads[0]["platform"] == "shopify_community"
        assert threads[0]["subreddit"] == "shopify-discussion"

    def test_pinned_topics_skipped(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={
            "topic_list": {
                "topics": [
                    {"id": 1, "title": "About this category", "slug": "about", "pinned": True, "like_count": 0, "reply_count": 0, "created_at": "2024-01-01T00:00:00.000Z"},
                    {"id": 2, "title": "Real topic", "slug": "real", "like_count": 1, "reply_count": 0, "created_at": "2024-01-01T00:00:00.000Z"},
                ],
            }
        })
        threads = scraper.scrape_category("shopify-discussion", 95, limit=10)
        assert len(threads) == 1
        assert threads[0]["thread_id"] == "sc_2"

    def test_respects_limit_across_pages(self, mocker):
        scraper = ShopifyCommunityScraper()
        page0 = {
            "topic_list": {
                "topics": [{"id": i, "title": f"T{i}", "slug": f"t{i}", "like_count": 0, "reply_count": 0, "created_at": "2024-01-01T00:00:00.000Z"} for i in range(30)],
                "more_topics_url": "/c/shopify-discussion/95?page=1",
            }
        }
        page1 = {
            "topic_list": {
                "topics": [{"id": 100 + i, "title": f"T{100+i}", "slug": f"t{100+i}", "like_count": 0, "reply_count": 0, "created_at": "2024-01-01T00:00:00.000Z"} for i in range(30)],
            }
        }
        mocker.patch.object(scraper, "_request", side_effect=[page0, page1])
        threads = scraper.scrape_category("shopify-discussion", 95, limit=35)
        assert len(threads) == 35

    def test_empty_topics_stops_pagination(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={"topic_list": {"topics": []}})
        threads = scraper.scrape_category("shopify-discussion", 95, limit=10)
        assert threads == []


class TestFetchTopic:
    def test_builds_thread_with_comments(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={
            "title": "T", "category_id": 217, "like_count": 2, "reply_count": 1,
            "created_at": "2024-01-01T00:00:00.000Z",
            "post_stream": {"posts": [
                {"username": "op", "cooked": "<p>op text</p>", "created_at": "2024-01-01T00:00:00.000Z"},
                {"username": "r1", "cooked": "<p>reply text</p>", "score": 5.0, "reply_to_post_number": 1, "created_at": "2024-01-02T00:00:00.000Z"},
            ]},
        })
        thread = scraper.fetch_topic("payments-shipping-fulfilment", "t-slug", 42)
        assert thread["thread_id"] == "sc_42"
        assert thread["body"] == "op text"
        assert thread["comments"][0]["parent_id"] == "1"

    def test_missing_topic_returns_none(self, mocker):
        scraper = ShopifyCommunityScraper()
        mocker.patch.object(scraper, "_request", return_value={})
        assert scraper.fetch_topic("cat", "slug", 1) is None


def test_default_categories_are_slug_to_id_dict():
    assert isinstance(DEFAULT_CATEGORIES, dict)
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in DEFAULT_CATEGORIES.items())
