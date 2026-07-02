"""Grounding-aware community thread classifier using Claude API.

Platform-aware for Reddit and Shopify Community threads (thread["platform"]).
Thread origination (generate_thread_suggestions) stays Reddit-only.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import anthropic

from db import (
    get_grounding_doc, get_thread, update_classification,
    get_unclassified_threads, get_subreddit_profile_data,
)

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "claude-sonnet-4-5-20250929")
CLASSIFIER_CONCURRENCY = int(os.environ.get("CLASSIFIER_CONCURRENCY", "8"))


def _community_label(thread: dict) -> str:
    """Human-readable community identifier for a thread, platform-aware."""
    platform = thread.get("platform", "reddit")
    sub = thread.get("subreddit", "unknown")
    if platform == "shopify_community":
        return f"Shopify Community board: {sub}"
    return f"Subreddit: r/{sub}"


def _platform_noun(thread: dict) -> str:
    """Short platform name for prompt text ("Reddit" vs "Shopify Community")."""
    return "Shopify Community" if thread.get("platform") == "shopify_community" else "Reddit"


def _engagement_rules_doc_key(thread: dict) -> str:
    """Which engagement-rules grounding doc applies to this thread's platform."""
    if thread.get("platform") == "shopify_community":
        return "shopify_community_engagement_rules"
    return "reddit_engagement_rules"


def _format_top_comments(comments_json: str, limit: int = 10) -> str:
    """Format top comments for the classification prompt."""
    try:
        comments = json.loads(comments_json) if isinstance(comments_json, str) else comments_json
    except (json.JSONDecodeError, TypeError):
        return "(no comments)"

    if not comments:
        return "(no comments)"

    # Sort by score, take top N
    sorted_comments = sorted(comments, key=lambda c: c.get("score", 0), reverse=True)[:limit]

    lines = []
    for c in sorted_comments:
        score = c.get("score", 0)
        author = c.get("author", "[deleted]")
        body = c.get("body", "")[:500]  # Truncate long comments
        depth = c.get("depth", 0)
        indent = "  " * depth
        lines.append(f"{indent}[{score} pts] u/{author}: {body}")

    return "\n".join(lines)


def classify_thread_data(thread: dict) -> dict:
    """Classify a single thread using Claude with grounding docs.

    Args:
        thread: Dict with thread data from database (must have thread_id, title, body, etc.)

    Returns:
        Classification dict with topic, entities, personas, sentiment, etc.
    """
    # Load grounding docs
    competitive = get_grounding_doc("competitive_positioning") or ""
    icp = get_grounding_doc("icp_personas") or ""
    geo = get_grounding_doc("geo_content_strategy") or ""

    comments_text = _format_top_comments(thread.get("comments_json", "[]"))

    # Split into a cacheable grounding-docs prefix and a per-thread suffix.
    # Anthropic prompt caching saves ~90% of input processing time on
    # subsequent calls within the 5-min cache window.
    grounding_block = f"""You are classifying a {_platform_noun(thread)} thread for Onramp Funds, a revenue-based financing company for ecommerce sellers (Amazon FBA, Shopify, multi-channel).

Use the following strategic context to inform your classification:

<competitive_context>
{competitive}
</competitive_context>

<icp_personas>
{icp}
</icp_personas>

<geo_strategy>
{geo}
</geo_strategy>"""

    thread_block = f"""Classify this thread:

<thread>
{_community_label(thread)}
Title: {thread.get('title', '')}
Body: {thread.get('body', '')}
Score: {thread.get('score', 0)} | Comments: {thread.get('num_comments', 0)} | Upvote ratio: {thread.get('upvote_ratio', 0)}
</thread>

<top_comments>
{comments_text}
</top_comments>

Return ONLY valid JSON (no markdown fences, no explanation) with this exact structure:
{{
  "topic": "product_comparison|financing_advice_request|cash_flow_problem|growth_capital|vendor_review|complaint|recommendation_request|general_discussion|how_to|vendor_evaluation|industry_news",
  "entities": {{
    "competitors": [
      {{"name": "string", "sentiment": "positive|negative|neutral|mixed", "context": "brief quote or summary"}}
    ],
    "platforms": ["list of platforms mentioned e.g. Amazon, Shopify, Walmart, TikTok Shop"],
    "concepts": ["list of financing concepts e.g. revenue-based financing, MCA, inventory loan, factoring"]
  }},
  "personas": {{
    "thread_author": "amazon_fba_seller|multi_channel_ecommerce|dtc_brand_owner|shopify_store_owner|small_business_owner|agency_consultant|finance_professional|unknown",
    "dominant_commenter_persona": "string",
    "persona_distribution": {{"persona_name": "count_as_number"}}
  }},
  "sentiment": {{
    "overall": "positive|negative|neutral|mixed|seeking_help",
    "onramp_funds": "positive|negative|neutral|not_mentioned",
    "competitor_sentiments": {{"competitor_name": "sentiment"}}
  }},
  "pain_points": ["list of specific pain points expressed in buyer language"],
  "buyer_language": ["list of exact phrases buyers use that are useful for messaging"],
  "geo_signals": {{
    "thread_authority": 0.85,
    "google_index_likely": true,
    "reddit_answers_eligible": true,
    "conversation_gap": true,
    "narrative_correction_opportunity": false,
    "narrative_issues": ["list of narrative problems from GEO strategy that apply"]
  }},
  "participation_priority": "urgent|high|medium|low|skip",
  "participation_reasoning": "One sentence explaining why this priority level"
}}"""

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": grounding_block,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": thread_block},
                ],
            }],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        result = json.loads(text)
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse classification JSON: {e}")
        logger.error(f"Raw response: {text[:500]}")
        return {"error": str(e), "participation_priority": "unscored"}
    except Exception as e:
        logger.error(f"Classification error: {e}")
        return {"error": str(e), "participation_priority": "unscored"}


def classify_batch(
    batch_size: int = 10,
    thread_ids: Optional[list[str]] = None,
    platform: Optional[str] = None,
) -> dict:
    """Classify a batch of threads concurrently.

    Anthropic calls run in parallel (CLASSIFIER_CONCURRENCY workers) so a
    25-thread batch completes in roughly 1/5 the wall time vs. serial. DB
    writes happen on the main thread after each worker returns to avoid
    SQLite write contention.

    Args:
        batch_size: Number of unclassified threads to process
        thread_ids: Specific thread IDs to classify (overrides batch_size)
        platform: Restrict the batch to this platform ("reddit",
            "shopify_community"). Ignored if thread_ids is given.

    Returns:
        Summary dict with counts and any errors
    """
    if thread_ids:
        threads = [get_thread(tid) for tid in thread_ids]
        threads = [t for t in threads if t is not None]
    else:
        threads = get_unclassified_threads(batch_size, platform=platform)

    if not threads:
        return {"classified": 0, "message": "No unclassified threads found"}

    def _classify_one(thread):
        tid = thread["thread_id"]
        logger.info(f"Classifying thread {tid}: {thread['title'][:60]}...")
        try:
            return (thread, classify_thread_data(thread), None)
        except Exception as e:
            return (thread, None, str(e))

    results = {"classified": 0, "errors": 0, "details": []}

    workers = min(CLASSIFIER_CONCURRENCY, len(threads))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for thread, classification, error in pool.map(_classify_one, threads):
            tid = thread["thread_id"]
            if error:
                results["errors"] += 1
                results["details"].append({"thread_id": tid, "error": error})
                continue
            if "error" in classification:
                results["errors"] += 1
                results["details"].append({
                    "thread_id": tid,
                    "error": classification["error"],
                })
                continue
            update_classification(tid, classification)
            results["classified"] += 1
            results["details"].append({
                "thread_id": tid,
                "title": thread["title"][:80],
                "topic": classification.get("topic"),
                "priority": classification.get("participation_priority"),
            })

    return results


def generate_participation_guide(thread_id: str) -> dict:
    """Generate a full participation recommendation for a thread.

    Loads all grounding docs (picking the platform-correct engagement-rules
    doc for the thread's platform) and generates:
    - Draft response in authentic voice for that platform
    - Narrative check
    - Competitor guidance
    - Link suggestions
    - Do/don't guidance
    """
    thread = get_thread(thread_id)
    if not thread:
        return {"error": f"Thread {thread_id} not found"}

    # Load all grounding docs. Engagement rules are platform-specific:
    # Shopify Community has materially different, platform-enforced
    # self-promotion and disclosure rules (see shopify_community_engagement_rules.md)
    # that don't transfer from Reddit's community norms.
    competitive = get_grounding_doc("competitive_positioning") or ""
    voice_tone = get_grounding_doc("voice_tone") or ""
    engagement_rules = get_grounding_doc(_engagement_rules_doc_key(thread)) or ""
    product = get_grounding_doc("product_messaging") or ""
    icp = get_grounding_doc("icp_personas") or ""
    geo = get_grounding_doc("geo_content_strategy") or ""

    classification_text = thread.get("classification", "Not yet classified")
    comments_text = _format_top_comments(thread.get("comments_json", "[]"), limit=15)

    # Pull aggregated community profile from our DB so the guide is
    # calibrated to the community we're posting in, not just the brand
    # docs. DB-only (no live network calls here) to keep the guide fast.
    # Scoped to this thread's platform so a same-named board/subreddit on
    # a different platform can't bleed into the profile.
    subreddit_profile = get_subreddit_profile_data(
        thread.get("subreddit") or "", platform=thread.get("platform", "reddit")
    )
    subreddit_profile_json = json.dumps(
        subreddit_profile, indent=2, default=str
    )[:4000]

    # Split into a cacheable grounding-docs block (all 6 brand docs, ~60KB)
    # and a per-thread block. With prompt caching, the 60KB only gets
    # processed once per 5-min window across all calls.
    grounding_block = f"""You are an expert {_platform_noun(thread)} strategist for Onramp Funds, a revenue-based financing platform for ecommerce sellers.

<competitive_positioning>
{competitive}
</competitive_positioning>

<voice_and_tone>
{voice_tone}
</voice_and_tone>

<engagement_rules>
{engagement_rules}
</engagement_rules>

<product_messaging>
{product}
</product_messaging>

<icp_personas>
{icp}
</icp_personas>

<geo_strategy>
{geo}
</geo_strategy>"""

    thread_block = f"""CRITICAL INSTRUCTION: DRAFT QUALITY GATE
Before writing any draft comment, re-read the STOP block at the top of the voice/tone guide.
Run the 7-item rewrite checklist against every draft before including it in the response.
Do not return a draft that fails any checklist item. Rewrite it until it passes.
Each suggested_response.text field must be 200 words or fewer.
Count the words before returning. If over 200, cut the weakest point and recount.

Generate a detailed participation guide for this {_platform_noun(thread)} thread.

PROCEDURE FOR EACH DRAFT IN suggested_responses:
1. Before writing the draft, re-read the STOP block at the top of the voice_and_tone document. Those are not guidelines. They are a hard gate.
2. Write the draft applying those rules during composition, not after. Specifically: keep it under 200 words, no em-dashes, no bold, no markdown headers, no forbidden AI-tell phrases.
3. Once the draft is written, run the 7-item rewrite gate from the voice_and_tone document against it. Every item must pass.
4. If any gate item fails, rewrite the draft and re-run the gate. Do not include a draft in suggested_responses that fails any gate item.
5. If a draft cannot pass all 7 gate items without major rewriting, the underlying response variant is wrong. Change the variant and try again.

<thread>
{_community_label(thread)}
Title: {thread.get('title')}
Body: {thread.get('body')}
Score: {thread.get('score')} | Comments: {thread.get('num_comments')}
URL: {thread.get('url')}
Classification: {classification_text}
</thread>

<subreddit_profile>
Aggregated profile of {thread.get('subreddit')} from our scraping history.
Use this to calibrate tone, register, and word choice to what this specific
community responds to. Pay attention to which competitors get mentioned and
the sentiment around them, the typical persona of the OP in this community, and
the topic mix.

{subreddit_profile_json}
</subreddit_profile>

<comments>
{comments_text}
</comments>

Return ONLY valid JSON with this structure:
{{
  "recommendation": "engage|monitor|skip",
  "priority": "urgent|high|medium|low",
  "reasoning": "Why this thread matters for Onramp Funds",

  "suggested_responses": [
    {{
      "variant": "peer_mode|expert_mode|helper_mode|corrective_mode",
      "text": "The full draft response text, written in authentic voice for this platform",
      "tone_notes": "Brief note on tone calibration"
    }}
  ],

  "narrative_check": {{
    "addresses_cash_flow_pain": true,
    "differentiates_from_mca": false,
    "highlights_ecommerce_specialization": false,
    "transparent_pricing": true,
    "narrative_issues_addressed": ["list from GEO strategy"]
  }},

  "competitor_guidance": {{
    "competitors_in_thread": ["list"],
    "response_protocol": "How to handle each competitor mention"
  }},

  "suggested_links": [
    {{
      "url": "https://www.onrampfunds.com/...",
      "context": "When and how to share this link",
      "mql_signal": "Any known MQL data"
    }}
  ],

  "do_not": ["list of things to avoid in this specific thread"],

  "timing": {{
    "thread_still_active": true,
    "optimal_post_window": "description of timing"
  }}
}}

FINAL CHECK BEFORE RETURNING THE JSON:

For each entry in suggested_responses, count the words in the text field. If any draft is over 200 words, you have not followed the procedure. Cut the weakest point and recount until under 200.

Scan each draft text for em-dashes. If you find any, you have not followed the procedure. Rewrite those sentences with commas or by splitting them in two.

Scan each draft text for bold markdown or headers. If you find any, you have not followed the procedure. Strip them.

Scan each draft text for any of these phrases: "Happy to answer specifics", "At your scale", "Real talk", "Hope that helps", "It's worth noting", "The reason I ask is", "The short answer is", "Honestly,", "That said,", "Feel free to reach out", "Happy to DM". If you find any, you have not followed the procedure. Rewrite to remove them.

The target register is the 130-word reference comment in the voice_and_tone grounding doc. Re-read it and compare against each of your drafts. If any draft has more AI fingerprints than the reference comment, rewrite it. Do not return drafts that look more AI-generated than that reference."""

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": grounding_block,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": thread_block},
                ],
            }],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
        guide = json.loads(text)
        guide["platform"] = thread.get("platform", "reddit")
        return guide
    except Exception as e:
        logger.error(f"Participation guide error: {e}")
        return {"error": str(e)}


def generate_thread_suggestions(
    topic: Optional[str] = None,
    persona: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Generate Reddit thread origination suggestions.

    Reddit-only by design. Shopify Community's self-promotion policy
    restricts anything solution-shaped to the Ask & Offer board (see
    shopify_community_engagement_rules.md), so unprompted "content marketing"
    thread origination doesn't map to that platform the way it does to Reddit.
    """
    geo = get_grounding_doc("geo_content_strategy") or ""
    competitive = get_grounding_doc("competitive_positioning") or ""
    icp = get_grounding_doc("icp_personas") or ""
    voice = get_grounding_doc("voice_tone") or ""

    focus = ""
    if topic:
        focus += f"Focus on topic: {topic}\n"
    if persona:
        focus += f"Target persona: {persona}\n"

    grounding_block = f"""You are a Reddit content strategist for Onramp Funds, a revenue-based financing platform for ecommerce sellers.

<geo_strategy>
{geo}
</geo_strategy>

<competitive_positioning>
{competitive}
</competitive_positioning>

<icp_personas>
{icp}
</icp_personas>

<voice_tone>
{voice}
</voice_tone>"""

    task_block = f"""Generate {limit} thread origination suggestions — threads Onramp Funds should create on Reddit to:
1. Rank in Google for target queries
2. Surface in Reddit Answers
3. Feed LLM training data with accurate Onramp Funds positioning
4. Build brand authority and community credibility with ecommerce sellers

{focus}

Return ONLY valid JSON array:
[
  {{
    "template": "what_i_learned|honest_comparison|regulatory_explainer|myth_busting|resource|ama",
    "title": "Exact Reddit post title",
    "body_draft": "Full post body text in authentic Reddit voice (300-500 words)",
    "target_subreddit": "r/subreddit",
    "target_persona": "persona_name",
    "geo_value_score": 0.85,
    "target_queries": ["Google queries this thread could rank for"],
    "narrative_corrections": ["Which GEO narrative issues this addresses"],
    "engagement_prediction": "high|medium|low",
    "follow_up_notes": "How to engage with comments after posting"
  }}
]"""

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": grounding_block,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": task_block},
                ],
            }],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Thread suggestion error: {e}")
        return [{"error": str(e)}]
