"""Brand profile loader.

Loads a YAML profile that defines everything brand-specific about the MCP
server's behavior: brand name, industry, default subreddits/keywords,
taxonomy (topics/personas/templates), grounding-doc keys, and prompt
templates.

Point MCP_PROFILE_PATH at a YAML file. If unset, falls back to
profiles/example.yaml in the repo root.
"""

import os
import logging
from pathlib import Path
from typing import Any
import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "profiles" / "example.yaml"


class Profile:
    """In-memory, read-only view of the active brand profile.

    Use `Profile.get()` for the singleton loaded at import time. Tests can
    override with `Profile.load(path)`.
    """

    _instance: "Profile | None" = None

    def __init__(self, data: dict[str, Any], source_path: Path):
        self._data = data
        self.source_path = source_path

    @classmethod
    def get(cls) -> "Profile":
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Profile":
        resolved = Path(path) if path else Path(
            os.environ.get("MCP_PROFILE_PATH", DEFAULT_PROFILE_PATH)
        )
        if not resolved.exists():
            raise FileNotFoundError(
                f"Profile not found: {resolved}. "
                f"Set MCP_PROFILE_PATH or copy profiles/example.yaml."
            )
        with resolved.open() as f:
            data = yaml.safe_load(f) or {}
        cls._instance = cls(data, resolved)
        logger.info(f"Loaded brand profile: {data.get('brand', {}).get('name', 'unknown')} from {resolved}")
        return cls._instance

    # --- Accessors ---

    @property
    def brand(self) -> dict:
        return self._data.get("brand", {})

    @property
    def brand_name(self) -> str:
        return self.brand.get("name", "the brand")

    @property
    def brand_slug(self) -> str:
        return self.brand.get("slug", "brand")

    @property
    def industry_context(self) -> str:
        return self.brand.get("industry_context", "")

    @property
    def brand_url(self) -> str:
        return self.brand.get("url", "")

    @property
    def defaults(self) -> dict:
        return self._data.get("defaults", {})

    @property
    def default_subreddits(self) -> list[str]:
        return self.defaults.get("subreddits", [])

    @property
    def default_keywords(self) -> list[str]:
        return self.defaults.get("keywords", [])

    @property
    def competitors(self) -> list[str]:
        return self.defaults.get("competitors", [])

    @property
    def supported_platforms(self) -> list[str]:
        return self.defaults.get("supported_platforms", [])

    @property
    def taxonomy(self) -> dict:
        return self._data.get("taxonomy", {})

    @property
    def topics(self) -> list[str]:
        return self.taxonomy.get("topics", [])

    @property
    def personas(self) -> list[str]:
        return self.taxonomy.get("personas", [])

    @property
    def thread_templates(self) -> list[str]:
        return self.taxonomy.get("thread_templates", [])

    @property
    def response_variants(self) -> list[str]:
        return self.taxonomy.get("response_variants", [])

    @property
    def grounding_doc_keys(self) -> list[str]:
        return self._data.get("grounding_doc_keys", [])

    @property
    def narrative_check_fields(self) -> list[str]:
        return self._data.get("narrative_check_fields", [])

    @property
    def compliance(self) -> dict:
        return self._data.get("compliance", {})

    @property
    def required_disclaimer(self) -> str:
        return self.compliance.get("required_disclaimer", "")

    @property
    def disclaimer_required(self) -> bool:
        return bool(self.compliance.get("required_disclaimer"))

    @property
    def compliance_guardrails(self) -> list[str]:
        return self.compliance.get("guardrails", [])

    @property
    def integrations(self) -> dict:
        return self._data.get("integrations", {})

    @property
    def citation_tracker(self) -> dict:
        return self.integrations.get("citation_tracker", {})

    @property
    def citation_tracker_enabled(self) -> bool:
        return bool(self.citation_tracker.get("enabled"))

    @property
    def citation_tracker_provider(self) -> str:
        return self.citation_tracker.get("provider", "")

    @property
    def prompts(self) -> dict:
        return self._data.get("prompts", {})

    def server_name(self) -> str:
        return self._data.get("server_name") or f"{self.brand_slug}_reddit_mcp"

    def raw(self) -> dict:
        return dict(self._data)


def get_profile() -> Profile:
    return Profile.get()
