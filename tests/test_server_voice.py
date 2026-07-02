"""Tests for server.py's voice/tone gate and the Shopify Community
no-links enforcement (the operating decision confirmed mid-session and
backed by a hard server-side check, not just a prompt instruction).
"""

import server


REFERENCE_COMMENT = (
    "Wholesale at that scale is basically a cash flow management business with some "
    "arbitrage on top. The Amazon float problem you're describing ($800K sitting in deferrals "
    "while your supplier wants payment) doesn't get better as you grow, it gets worse. SBA is the "
    "right long-term play if you can qualify and wait. The gap filler most sellers in your situation "
    "use is revenue-based financing. You pay it back as a percentage of daily sales so it flexes when "
    "Amazon holds funds longer than expected. More expensive than SBA, funded in a day or two. I'm at "
    "Onramp Funds so I'm biased, but Wayflyer and Settle both serve this scale too. What's your current "
    "DSO from supplier payment to Amazon release?"
)


class TestVoiceIssuesCommentMode:
    def test_reference_comment_passes_clean(self):
        result = server._voice_issues(REFERENCE_COMMENT, mode="comment")
        assert result == {"hard": [], "soft": []}

    def test_em_dash_is_hard_violation(self):
        result = server._voice_issues("This is a test — with an em-dash.", mode="comment")
        assert any("em-dash" in v for v in result["hard"])

    def test_over_200_words_is_hard_violation(self):
        text = "word " * 201
        result = server._voice_issues(text, mode="comment")
        assert any("word_count" in v for v in result["hard"])

    def test_forbidden_phrase_is_hard_violation(self):
        result = server._voice_issues("Honestly, that's a good question.", mode="comment")
        assert any("AI-tell phrases" in v for v in result["hard"])

    def test_marketing_word_is_soft_only(self):
        text = ("Revenue-based financing means you pay back a percentage of daily sales. "
                "I work at Onramp and this kind of solution fits restock gaps well. "
                "What's your current monthly revenue?")
        result = server._voice_issues(text, mode="comment")
        assert result["hard"] == []
        assert any("marketing language" in v for v in result["soft"])

    def test_names_onramp_without_disclosure_is_hard(self):
        result = server._voice_issues(
            "Onramp does revenue-based financing. What's your monthly revenue?", mode="comment",
        )
        assert any("without affiliation disclosure" in v for v in result["hard"])

    def test_private_conversation_ending_is_hard(self):
        result = server._voice_issues(
            "Payout gaps are common. Happy to DM if you want details.", mode="comment",
        )
        assert any("private-conversation offer" in v for v in result["hard"])


class TestVoiceIssuesPostMode:
    def test_post_mode_allows_headers_and_lists(self):
        text = (
            "## The payout gap\n"
            "Amazon holds funds for about two weeks.\n"
            "1. Plan early.\n"
            "2. Watch your IPI.\n"
            "I work at Onramp so take that with context. What is everyone using this year?"
        )
        result = server._voice_issues(text, mode="post")
        assert not any("markdown header" in v for v in result["hard"])
        assert not any("numbered/parenthetical list" in v for v in result["hard"])

    def test_post_mode_runaway_length_guard(self):
        text = "word " * 600
        result = server._voice_issues(text, mode="post")
        assert any("runaway guard" in v for v in result["hard"])

    def test_post_mode_still_catches_em_dash(self):
        result = server._voice_issues("A post with an em-dash — right here.", mode="post")
        assert any("em-dash" in v for v in result["hard"])


class TestNoLinksEnforcement:
    def test_url_is_hard_violation_when_no_links_true(self):
        result = server._voice_issues(
            "Check https://onrampfunds.com/compare for details.", mode="comment", no_links=True,
        )
        assert any("no-links policy" in v for v in result["hard"])

    def test_bare_domain_is_hard_violation_when_no_links_true(self):
        result = server._voice_issues(
            "Check onrampfunds.com for details.", mode="comment", no_links=True,
        )
        assert any("no-links policy" in v for v in result["hard"])

    def test_same_text_is_fine_on_reddit(self):
        # Links are situationally fine on Reddit — no_links defaults False.
        result = server._voice_issues(
            "Check https://onrampfunds.com/compare for the fee structure.", mode="comment",
        )
        assert not any("no-links policy" in v for v in result["hard"])

    def test_link_free_shopify_draft_passes(self):
        text = (
            "Payout gaps on Amazon usually run about two weeks. The fix most sellers use is "
            "revenue-based financing, where the payment scales with your daily sales. I'm with "
            "Onramp Funds so I'm biased here. What's your current gap between payout and needing to restock?"
        )
        result = server._voice_issues(text, mode="comment", no_links=True)
        assert result["hard"] == []


class TestVoiceWarningBlock:
    def test_clean_draft_returns_none(self):
        assert server._voice_warning_block(REFERENCE_COMMENT, mode="comment") is None

    def test_hard_violation_sets_passes_gate_false(self):
        block = server._voice_warning_block("Honestly, that's a good question.", mode="comment")
        assert block["passes_gate"] is False
        assert block["hard_violations"]

    def test_soft_only_sets_passes_gate_true(self):
        text = ("This kind of solution fits restock gaps. I'm at Onramp Funds so I'm biased. "
                "What's your monthly revenue?")
        block = server._voice_warning_block(text, mode="comment")
        assert block is not None
        assert block["passes_gate"] is True
        assert block["hard_violations"] == []
        assert block["soft_warnings"]


class TestCheckResponseVoice:
    def test_shopify_platform_triggers_no_links_check(self):
        guide = {
            "platform": "shopify_community",
            "suggested_responses": [{
                "variant": "helper_mode",
                "text": "Check onrampfunds.com for details, or visit https://onrampfunds.com/compare.",
            }],
        }
        warnings = server._check_response_voice(guide)
        assert len(warnings) == 1
        assert any("no-links policy" in v for v in warnings[0]["hard_violations"])

    def test_reddit_platform_does_not_trigger_no_links_check(self):
        guide = {
            "platform": "reddit",
            "suggested_responses": [{
                "variant": "helper_mode",
                "text": "I'm at Onramp Funds so I'm biased, but check onrampfunds.com/compare for the fee structure. What's your monthly revenue?",
            }],
        }
        warnings = server._check_response_voice(guide)
        assert warnings == []

    def test_missing_platform_key_defaults_to_reddit_behavior(self):
        # A guide dict without "platform" (e.g. from an older code path or
        # an error path) must not be treated as Shopify Community by
        # accident — that would wrongly flag legitimate Reddit links.
        guide = {
            "suggested_responses": [{
                "variant": "helper_mode",
                "text": "I'm at Onramp Funds so I'm biased, but check onrampfunds.com/compare. What's your revenue?",
            }],
        }
        warnings = server._check_response_voice(guide)
        assert warnings == []

    def test_empty_suggested_responses(self):
        assert server._check_response_voice({"platform": "reddit"}) == []
