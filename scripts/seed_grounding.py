"""Seed grounding documents from a directory of .md files into the database.

Usage:
    python scripts/seed_grounding.py grounding/
    python scripts/seed_grounding.py private/grounding/

Each .md file becomes one grounding_doc row, keyed by its filename (without
the .md extension). The first H1 (# ...) is used as the title; if missing,
the filename is used.

Idempotent — run it as often as you like. Files that already exist in the
database get their content updated.
"""

import sys
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import store_grounding_doc


def extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def main(directory: str):
    path = Path(directory)
    if not path.is_dir():
        print(f"ERROR: not a directory: {directory}")
        sys.exit(1)

    md_files = sorted(path.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {directory}")
        return

    for md in md_files:
        doc_key = md.stem
        content = md.read_text()
        title = extract_title(content, doc_key.replace("_", " ").title())
        store_grounding_doc(
            doc_key=doc_key,
            title=title,
            content=content,
            doc_type="reference",
            source_url=None,
        )
        print(f"  seeded: {doc_key}  ({len(content):,} chars)  \"{title}\"")

    print(f"\nDone. Seeded {len(md_files)} doc(s) from {directory}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/seed_grounding.py <grounding-dir>")
        sys.exit(2)
    main(sys.argv[1])
