"""Profile-aware Reddit thread classifier using Claude API.

All brand-specific language is pulled from the active profile at render time.
This module itself contains no brand strings.
"""

import json
import logging
import os
from typing import Optional
import anthropic

from db import (
    get_grounding_doc, get_thread, update_classification,
    get_unclassified_threads, get_relevant_feedback,
)
from profile import get_profile
from prompts import (
    render_classifier_prompt,
    render_participation_prompt,
    render_thread_suggestions_prompt,
)

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "claude-sonnet-4-5-20250929")


def _format_top_comments(comments_json: str, limit: int = 10) -> str:
    try:
        comments = json.loads(comments_json) if isinstance(comments_json, str) else comments_json
    except (json.JSONDecodeError, TypeError):
        return "(no comments)"
    if not comments:
        return "(no comments)"

    sorted_comments = sorted(comments, key=lambda c: c.get("score", 0), reverse=True)[:limit]
    lines = []
    for c in sorted_comments:
        score = c.get("score", 0)
        author = c.get("author", "[deleted]")
        body = c.get("body", "")[:500]
        depth = c.get("depth", 0)
        indent = "  " * depth
        lines.append(f"{indent}[{score} pts] u/{author}: {body}")
    return "\n".join(lines)


def _load_grounding(keys: list[str]) -> dict[str, str]:
    """Load all grounding docs declared in the profile."""
    return {key: (get_grounding_doc(key) or "") for key in keys}


def _parse_json_response(text: str) -> dict | list:
    """Strip common wrappers (markdown fences, leading 'json' labels) and parse."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    return json.loads(text)


def classify_thread_data(thread: dict) -> dict:
    """Classify a single thread using Claude, grounded in profile docs."""
    profile = get_profile()
    grounding = _load_grounding(profile.grounding_doc_keys)
    comments_text = _format_top_comments(thread.get("comments_json", "[]"))
    prompt = render_classifier_prompt(
        thread, comments_text, profile=profile, grounding_docs=grounding,
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return _parse_json_response(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse classification JSON: {e}")
        return {"error": str(e), "participation_priority": "unscored"}
    except Exception as e:
        logger.error(f"Classification error: {e}")
        return {"error": str(e), "participation_priority": "unscored"}


def classify_batch(batch_size: int = 10, thread_ids: Optional[list[str]] = None) -> dict:
    """Classify a batch of threads."""
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
    """Generate a participation recommendation for a thread.

    Pulls grounding docs + recent human edits (feedback) and injects both
    into the prompt so the model learns from past corrections.
    """
    thread = get_thread(thread_id)
    if not thread:
        return {"error": f"Thread {thread_id} not found"}

    profile = get_profile()
    grounding = _load_grounding(profile.grounding_doc_keys)
    classification_text = thread.get("classification", "Not yet classified")
    comments_text = _format_top_comments(thread.get("comments_json", "[]"), limit=15)

    feedback_examples = get_relevant_feedback(
        tool_name="reddit_participation_guide",
        subreddit=thread.get("subreddit"),
        limit=5,
    )

    prompt = render_participation_prompt(
        thread=thread,
        comments_text=comments_text,
        classification_text=classification_text,
        profile=profile,
        grounding_docs=grounding,
        feedback_examples=feedback_examples,
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        result = _parse_json_response(text)
        if isinstance(result, dict):
            result["_meta"] = {
                "feedback_examples_applied": len(feedback_examples),
                "brand": profile.brand_name,
            }
        return result
    except Exception as e:
        logger.error(f"Participation guide error: {e}")
        return {"error": str(e)}


def generate_thread_suggestions(
    topic: Optional[str] = None,
    persona: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Generate thread origination suggestions."""
    profile = get_profile()
    grounding = _load_grounding(profile.grounding_doc_keys)
    prompt = render_thread_suggestions_prompt(
        topic=topic, persona=persona, limit=limit,
        profile=profile, grounding_docs=grounding,
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        result = _parse_json_response(text)
        return result if isinstance(result, list) else [{"error": "Expected array", "raw": text[:500]}]
    except Exception as e:
        logger.error(f"Thread suggestion error: {e}")
        return [{"error": str(e)}]
