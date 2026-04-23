"""Prompt templates.

All LLM prompts live here, parameterized by the active brand profile.
No Osano/Onramp/etc. strings in this file — everything is substituted
from profile.yaml at render time.
"""

from typing import Optional
from profile import Profile, get_profile


def _pipe(values: list[str]) -> str:
    """Format a list as a pipe-separated enum for JSON schema hints."""
    return "|".join(values) if values else "unknown"


def _tag_section(tag: str, body: str) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    return f"<{tag}>\n{body}\n</{tag}>\n"


def render_classifier_prompt(
    thread: dict,
    comments_text: str,
    profile: Optional[Profile] = None,
    grounding_docs: Optional[dict[str, str]] = None,
) -> str:
    """Build the thread-classification prompt."""
    p = profile or get_profile()
    g = grounding_docs or {}

    topics = _pipe(p.topics or [
        "product_comparison", "implementation_help", "complaint",
        "recommendation_request", "general_discussion", "how_to",
        "vendor_evaluation", "industry_news",
    ])
    personas = _pipe((p.personas or ["unknown"]) + ["unknown"])
    sentiments = "positive|negative|neutral|mixed|seeking_help"
    brand_sentiment_values = "positive|negative|neutral|not_mentioned"
    brand_sentiment_key = p.brand_slug

    role = p.prompts.get("classifier_role") or (
        f"You are classifying a Reddit thread for {p.brand_name}"
        + (f", which provides {p.industry_context}." if p.industry_context else ".")
    )

    sections = [role, ""]
    for key in p.grounding_doc_keys:
        if key in g and g[key]:
            sections.append(_tag_section(key, g[key]))

    sections.append(f"""Classify this thread:

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
  "topic": "{topics}",
  "entities": {{
    "competitors": [
      {{"name": "string", "sentiment": "positive|negative|neutral|mixed", "context": "brief quote or summary"}}
    ],
    "platforms": ["platforms mentioned, e.g. {', '.join(p.supported_platforms[:5]) if p.supported_platforms else 'Shopify, Amazon'}"],
    "concepts": ["domain-specific concepts mentioned"]
  }},
  "personas": {{
    "thread_author": "{personas}",
    "dominant_commenter_persona": "string",
    "persona_distribution": {{"persona_name": "count_as_number"}}
  }},
  "sentiment": {{
    "overall": "{sentiments}",
    "{brand_sentiment_key}": "{brand_sentiment_values}",
    "competitor_sentiments": {{"competitor_name": "sentiment"}}
  }},
  "pain_points": ["list of specific pain points in buyer language"],
  "buyer_language": ["exact phrases buyers use that are useful for messaging"],
  "signals": {{
    "thread_authority": 0.85,
    "google_index_likely": true,
    "reddit_answers_eligible": true,
    "conversation_gap": true,
    "narrative_correction_opportunity": false,
    "narrative_issues": ["list of narrative problems that apply"]
  }},
  "participation_priority": "urgent|high|medium|low|skip",
  "participation_reasoning": "One sentence explaining why this priority level"
}}""")
    return "\n".join(s for s in sections if s)


def render_participation_prompt(
    thread: dict,
    comments_text: str,
    classification_text: str,
    profile: Optional[Profile] = None,
    grounding_docs: Optional[dict[str, str]] = None,
    feedback_examples: Optional[list[dict]] = None,
) -> str:
    """Build the participation-guide prompt with optional few-shot examples
    from past human edits."""
    p = profile or get_profile()
    g = grounding_docs or {}

    role = p.prompts.get("participation_role") or (
        f"You are an expert Reddit strategist for {p.brand_name}."
    )

    variants = _pipe(p.response_variants or ["peer_mode", "expert_mode", "helper_mode", "corrective_mode"])

    narrative_fields_json = "\n    ".join(
        f'"{field}": true,' for field in (p.narrative_check_fields or [])
    )
    narrative_block = (
        "{\n    " + narrative_fields_json + '\n    "narrative_issues_addressed": ["list of applicable narrative issues"]\n  }'
        if narrative_fields_json
        else '{"narrative_issues_addressed": ["list of applicable narrative issues"]}'
    )

    sections = [role, ""]

    # Grounding docs — injected in the order declared in the profile
    for key in p.grounding_doc_keys:
        if key in g and g[key]:
            sections.append(_tag_section(key, g[key]))

    # Compliance guardrails — separate section so the model can't miss it
    if p.disclaimer_required or p.compliance_guardrails:
        compliance_body = ""
        if p.compliance_guardrails:
            compliance_body += "HARD RULES:\n" + "\n".join(f"- {g}" for g in p.compliance_guardrails) + "\n"
        if p.required_disclaimer:
            compliance_body += (
                f"\nREQUIRED DISCLAIMER (must appear verbatim somewhere in every suggested_response "
                f"when the thread involves financing, pricing, or eligibility):\n"
                f"\"{p.required_disclaimer}\"\n"
            )
        sections.append(_tag_section("compliance", compliance_body))

    # Few-shot: how humans actually edited past drafts
    if feedback_examples:
        shots = []
        for ex in feedback_examples[:5]:
            shots.append(
                f"--- Example {len(shots)+1} ---\n"
                f"Thread: r/{ex.get('subreddit', '')} — {ex.get('thread_title', '')[:120]}\n"
                f"ORIGINAL DRAFT:\n{ex.get('original_text', '')[:800]}\n\n"
                f"WHAT WE ACTUALLY POSTED:\n{ex.get('final_text', '')[:800]}\n\n"
                f"REASON FOR EDITS: {ex.get('reason', '(none given)')}"
            )
        sections.append(_tag_section("learned_preferences", "\n\n".join(shots) +
            "\n\nApply these edit patterns to the new draft below. If the user explicitly flagged "
            "something as a 'don't' in past reasons, do not repeat it."))

    sections.append(f"""Generate a detailed participation guide for this Reddit thread.

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
  "reasoning": "Why this thread matters for {p.brand_name}",

  "suggested_responses": [
    {{
      "variant": "{variants}",
      "text": "Full draft response in authentic Reddit voice",
      "tone_notes": "Brief note on tone calibration",
      "includes_disclaimer": true
    }}
  ],

  "narrative_check": {narrative_block},

  "competitor_guidance": {{
    "competitors_in_thread": ["list"],
    "response_protocol": "How to handle each competitor mention"
  }},

  "suggested_links": [
    {{"url": "https://...", "context": "When and how to share"}}
  ],

  "do_not": ["things to avoid in this specific thread"],

  "timing": {{
    "thread_still_active": true,
    "optimal_post_window": "description"
  }}
}}""")
    return "\n".join(s for s in sections if s)


def render_thread_suggestions_prompt(
    topic: Optional[str],
    persona: Optional[str],
    limit: int,
    profile: Optional[Profile] = None,
    grounding_docs: Optional[dict[str, str]] = None,
) -> str:
    """Build the thread-origination suggestions prompt."""
    p = profile or get_profile()
    g = grounding_docs or {}

    role = p.prompts.get("origination_role") or (
        f"You are a Reddit content strategist for {p.brand_name}."
    )

    templates = _pipe(p.thread_templates or [
        "what_i_learned", "honest_comparison", "myth_busting", "resource", "ama",
    ])

    focus = ""
    if topic:
        focus += f"Focus on topic: {topic}\n"
    if persona:
        focus += f"Target persona: {persona}\n"

    sections = [
        role,
        "",
        f"""Generate {limit} thread origination suggestions — threads {p.brand_name} should create on Reddit to:
1. Rank in Google for target queries
2. Surface in Reddit Answers and AI search results
3. Feed LLM training data with accurate {p.brand_name} positioning
4. Build brand authority and community credibility""",
        focus,
    ]
    for key in p.grounding_doc_keys:
        if key in g and g[key]:
            sections.append(_tag_section(key, g[key]))

    if p.required_disclaimer:
        sections.append(_tag_section(
            "compliance",
            f"Every body_draft must include this disclaimer verbatim:\n\"{p.required_disclaimer}\""
        ))

    sections.append(f"""Return ONLY a valid JSON array:
[
  {{
    "template": "{templates}",
    "title": "Exact Reddit post title",
    "body_draft": "Full post body text in authentic Reddit voice (300-500 words)",
    "target_subreddit": "r/subreddit",
    "target_persona": "persona_name",
    "seo_value_score": 0.85,
    "target_queries": ["Google queries this could rank for"],
    "narrative_corrections": ["which narrative issues this addresses"],
    "engagement_prediction": "high|medium|low",
    "follow_up_notes": "How to engage with comments after posting"
  }}
]""")
    return "\n".join(s for s in sections if s)
