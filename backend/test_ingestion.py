"""Standalone lore ingestion test.

Loads the short-story fixture, runs LoreAgent, and prints structured JSON.
"""

from __future__ import annotations

from pathlib import Path

from lore_agent import LoreAgent

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "short_story.txt"


def main() -> None:
    story = FIXTURE_PATH.read_text(encoding="utf-8")
    print(f"Loaded fixture: {FIXTURE_PATH}")
    print("--- raw text ---")
    print(story.strip())
    print("--- lore graph json ---")
    print(LoreAgent().ingest_to_json(story, source_title=FIXTURE_PATH.name))


if __name__ == "__main__":
    main()
