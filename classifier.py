"""Grounding-aware Reddit thread classifier using Claude API."""

import json
import logging
import os
from typing import Optional
import anthropic

from db import get_grounding_doc, get_thread, update_classification, get_unclassified_threads

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "claude-sonnet-4-5-20250929")


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

    prompt = f"""You are classifying a Reddit thread for Osano, a privacy compliance technology company.

Use the following strategic context to inform your classification:

<competitive_context>
{competitive}
</competitive_context>

<icp_personas>
{icp}
</icp_personas>

<geo_strategy>
{geo}
</geo_strategy>

Classify this thread:

<thread>
Subreddit: r/{thread.get('subreddit', 'unknown')}
Title: {thread.get('title', '')}
Body: {thread.get('body', '')}
Score: {thread.get('score', 0)} | Comments: {thread.get('num_comments', 0)} | Upvote ratio: {thread.get('upvote_ratio', 0)}
</thread>

<top_comments>
{comments_text}
</top_comments>

Return ONLY valid JSON (no markdown fences, no explanation) with this exact structure:
{{
  "topic": "product_comparison|implementation_help|regulatory_news|complaint|recommendation_request|general_discussion|how_to|vendor_evaluation|industry_news",
  "entities": {{
    "competitors": [
      {{"name": "string", "sentiment": "positive|negative|neutral|mixed", "context": "brief quote or summary"}}
    ],
    "regulations": ["list of regulations mentioned e.g. GDPR, CCPA"],
    "platforms": ["list of platforms mentioned e.g. WordPress, Shopify"],
    "concepts": ["list of privacy concepts e.g. cookie consent, DSAR, data mapping"]
  }},
  "personas": {{
    "thread_author": "non_privacy_expert|privacy_professional|developer_implementer|grc_legal|agency_consultant|unknown",
    "dominant_commenter_persona": "string",
    "persona_distribution": {{"persona_name": "count_as_number"}}
  }},
  "sentiment": {{
    "overall": "positive|negative|neutral|mixed|seeking_help",
    "osano": "positive|negative|neutral|not_mentioned",
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
            messages=[{"role": "user", "content": prompt}],
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


def classify_batch(batch_size: int = 10, thread_ids: Optional[list[str]] = None) -> dict:
    """Classify a batch of threads.

    Args:
        batch_size: Number of unclassified threads to process
        thread_ids: Specific thread IDs to classify (overrides batch_size)

    Returns:
        Summary dict with counts and any errors
    """
    if thread_ids:
        threads = [get_thread(tid) for tid in thread_ids]
        threads = [t for t in threads if t is not None]
    else:
        threads = get_unclassified_threads(batch_size)

    if not threads:
        return {"classified": 0, "message": "No unclassified threads found"}

    results = {"classified": 0, "errors": 0, "details": []}

    for thread in threads:
        tid = thread["thread_id"]
        logger.info(f"Classifying thread {tid}: {thread['title'][:60]}...")
        try:
            classification = classify_thread_data(thread)
            if "error" not in classification:
                update_classification(tid, classification)
                results["classified"] += 1
                results["details"].append({
                    "thread_id": tid,
                    "title": thread["title"][:80],
                    "topic": classification.get("topic"),
                    "priority": classification.get("participation_priority"),
                })
            else:
                results["errors"] += 1
                results["details"].append({
                    "thread_id": tid,
                    "error": classification["error"],
                })
        except Exception as e:
            results["errors"] += 1
            results["details"].append({"thread_id": tid, "error": str(e)})

    return results


def generate_participation_guide(thread_id: str) -> dict:
    """Generate a full participation recommendation for a thread.

    Loads ALL grounding docs and generates:
    - Draft response in Reddit voice
    - Narrative check
    - Competitor guidance
    - Link suggestions
    - Do/don't guidance
    """
    thread = get_thread(thread_id)
    if not thread:
        return {"error": f"Thread {thread_id} not found"}

    # Load all grounding docs
    competitive = get_grounding_doc("competitive_positioning") or ""
    voice_tone = get_grounding_doc("voice_tone") or ""
    engagement_rules = get_grounding_doc("reddit_engagement_rules") or ""
    product = get_grounding_doc("product_messaging") or ""
    icp = get_grounding_doc("icp_personas") or ""
    geo = get_grounding_doc("geo_content_strategy") or ""

    classification_text = thread.get("classification", "Not yet classified")
    comments_text = _format_top_comments(thread.get("comments_json", "[]"), limit=15)

    prompt = f"""You are an expert Reddit strategist for Osano, a privacy compliance platform.

Generate a detailed participation guide for this Reddit thread.

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
</geo_strategy>

<thread>
Subreddit: r/{thread.get('subreddit')}
Title: {thread.get('title')}
Body: {thread.get('body')}
Score: {thread.get('score')} | Comments: {thread.get('num_comments')}
URL: {thread.get('url')}
Classification: {classification_text}
</thread>

<comments>
{comments_text}
</comments>

Return ONLY valid JSON with this structure:
{{
  "recommendation": "engage|monitor|skip",
  "priority": "urgent|high|medium|low",
  "reasoning": "Why this thread matters for Osano",

  "suggested_responses": [
    {{
      "variant": "peer_mode|expert_mode|helper_mode|corrective_mode",
      "text": "The full draft response text, written in authentic Reddit voice",
      "tone_notes": "Brief note on tone calibration"
    }}
  ],

  "narrative_check": {{
    "corrects_cookie_only": true,
    "mentions_full_platform": false,
    "enterprise_positioning": false,
    "ease_of_use": true,
    "narrative_issues_addressed": ["list from GEO strategy"]
  }},

  "competitor_guidance": {{
    "competitors_in_thread": ["list"],
    "response_protocol": "How to handle each competitor mention"
  }},

  "suggested_links": [
    {{
      "url": "https://www.osano.com/...",
      "context": "When and how to share this link",
      "mql_signal": "Any known MQL data"
    }}
  ],

  "do_not": ["list of things to avoid in this specific thread"],

  "timing": {{
    "thread_still_active": true,
    "optimal_post_window": "description of timing"
  }}
}}"""

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
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
        logger.error(f"Participation guide error: {e}")
        return {"error": str(e)}


def generate_thread_suggestions(
    topic: Optional[str] = None,
    persona: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Generate thread origination suggestions."""
    geo = get_grounding_doc("geo_content_strategy") or ""
    competitive = get_grounding_doc("competitive_positioning") or ""
    icp = get_grounding_doc("icp_personas") or ""
    voice = get_grounding_doc("voice_tone") or ""

    focus = ""
    if topic:
        focus += f"Focus on topic: {topic}\n"
    if persona:
        focus += f"Target persona: {persona}\n"

    prompt = f"""You are a Reddit content strategist for Osano, a privacy compliance platform.

Generate {limit} thread origination suggestions — threads Osano should create on Reddit to:
1. Rank in Google for target queries
2. Surface in Reddit Answers
3. Feed LLM training data with accurate Osano positioning
4. Build brand authority and community credibility

{focus}

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
</voice_tone>

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
            messages=[{"role": "user", "content": prompt}],
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
