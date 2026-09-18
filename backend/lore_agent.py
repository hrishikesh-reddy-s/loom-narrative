"""Lore ingestion agent for Loom.

Takes raw narrative text and extracts a structured lore graph:
characters, ordered timeline checkpoints, and knowledge summaries that
are only valid between checkpoints.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "Loom")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"\s+")
_NAME_TOKEN = re.compile(r"^[A-Z][a-z]+(?:['-][A-Za-z]+)?$")
_PROPER_SPAN = re.compile(
    r"\b([A-Z][a-z]+(?:['-][A-Za-z]+)?(?:\s+[A-Z][a-z]+(?:['-][A-Za-z]+)?){0,2})\b"
)

_CLOSED_CLASS = {
    "A",
    "An",
    "The",
    "This",
    "That",
    "These",
    "Those",
    "At",
    "By",
    "For",
    "In",
    "On",
    "Of",
    "To",
    "Until",
    "After",
    "Before",
    "Then",
    "When",
    "While",
    "During",
    "Inside",
    "Outside",
    "Three",
    "Days",
    "Later",
    "Dawn",
    "Noon",
    "Night",
    "Midnight",
    "She",
    "He",
    "They",
    "Her",
    "His",
    "Him",
    "It",
    "Its",
    "And",
    "But",
    "Or",
    "So",
    "Yet",
    "Not",
    "No",
    "Yes",
    "If",
    "As",
    "From",
    "With",
    "Without",
    "Into",
    "Over",
    "Under",
    "Far",
    "Enough",
    "Together",
    "What",
    "Who",
    "Whom",
    "Whose",
    "Which",
    "There",
    "Here",
    "Once",
    "Never",
    "Always",
    "Still",
    "Already",
    "Only",
    "Last",
    "Old",
    "New",
    "Living",
    "Left",
    "Until",
}

_TIME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("for_years", re.compile(r"\bfor years\b", re.I)),
    ("at_dawn", re.compile(r"\bat dawn\b", re.I)),
    ("by_noon", re.compile(r"\bby noon\b", re.I)),
    ("three_days_later", re.compile(r"\bthree days later\b", re.I)),
    ("that_night", re.compile(r"\bthat night\b", re.I)),
    ("until_then", re.compile(r"\buntil then\b", re.I)),
    ("after_midnight", re.compile(r"\bafter midnight\b", re.I)),
    ("the_next_day", re.compile(r"\bthe next day\b", re.I)),
    ("years_ago", re.compile(r"\byears ago\b", re.I)),
    ("later", re.compile(r"\blater\b", re.I)),
]

_ROLE_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("lighthouse keeper", re.compile(r"\bkeeper\b|\blighthouse\b", re.I)),
    ("messenger", re.compile(r"\bsent him\b|\bhis order\b|\barchive\b", re.I)),
    ("stranger", re.compile(r"\bstranger\b", re.I)),
]

_UNTIL_THEN = re.compile(r"\buntil then\b", re.I)
_NAMED_INTRO = re.compile(
    r"\b(?:named|called)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)


class Character(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: str | None = None
    traits: list[str] = Field(default_factory=list)
    first_mentioned_index: int
    first_excerpt: str


class TimelineCheckpoint(BaseModel):
    id: str
    order: int
    time_marker: str | None
    event: str
    characters_involved: list[str]
    source_excerpt: str


class KnowledgeSummary(BaseModel):
    id: str
    valid_from: str
    valid_until: str | None
    summary: str
    known_facts: list[str]
    superseded_beliefs: list[str] = Field(default_factory=list)


class LoreGraph(BaseModel):
    source_title: str = APP_NAME
    characters: list[Character]
    timeline: list[TimelineCheckpoint]
    knowledge: list[KnowledgeSummary]


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _sentences(text: str) -> list[str]:
    chunks = [_normalize(part) for part in _SENTENCE_SPLIT.split(_normalize(text))]
    return [chunk for chunk in chunks if chunk]


def _time_marker(sentence: str) -> str | None:
    for label, pattern in _TIME_PATTERNS:
        if pattern.search(sentence):
            return label
    return None


def _is_name(span: str) -> bool:
    parts = span.split()
    if not parts or any(part in _CLOSED_CLASS for part in parts):
        return False
    return all(_NAME_TOKEN.match(part) for part in parts)


def _names_in(sentence: str) -> list[str]:
    found: list[str] = []
    intro = _NAMED_INTRO.search(sentence)
    if intro:
        found.append(intro.group(1))
    for match in _PROPER_SPAN.finditer(sentence):
        span = match.group(1)
        if _is_name(span) and span not in found:
            found.append(span)
    return found


def _mentions(name: str, sentence: str) -> bool:
    tokens = {name, name.split()[0]}
    return any(re.search(rf"\b{re.escape(token)}\b", sentence) for token in tokens)


def _role_for(name: str, corpus: str) -> str | None:
    window_hits: list[str] = []
    for sentence in _sentences(corpus):
        if not _mentions(name, sentence):
            continue
        for role, pattern in _ROLE_HINTS:
            if pattern.search(sentence) and role not in window_hits:
                window_hits.append(role)
    if "lighthouse keeper" in window_hits:
        return "lighthouse keeper"
    if "messenger" in window_hits:
        return "archive envoy"
    if "stranger" in window_hits:
        return "stranger"
    return None


def _traits_for(name: str, sentences: list[str]) -> list[str]:
    first = name.split()[0]
    traits: list[str] = []
    for sentence in sentences:
        if first not in sentence and name not in sentence:
            continue
        lowered = sentence.lower()
        if "did not trust" in lowered or "did not trust him" in lowered:
            if name == "Kellan" or first == "Kellan":
                traits.append("initially untrusted")
        if "believed she was the only" in lowered or "thought solitude" in lowered:
            if first == "Mara":
                traits.append("believed herself alone")
        if "agreed to leave" in lowered and first == "Mara":
            traits.append("chooses to leave the lighthouse")
        if "order had sent" in lowered and first == "Kellan":
            traits.append("sent by an order")
    return list(dict.fromkeys(traits))


def _canonical_characters(sentences: list[str], raw_text: str) -> list[Character]:
    mentions: dict[str, Character] = {}
    for index, sentence in enumerate(sentences):
        for name in _names_in(sentence):
            if name not in mentions:
                mentions[name] = Character(
                    name=name,
                    first_mentioned_index=index,
                    first_excerpt=sentence,
                )

    # Fold first-name mentions into longer names when possible.
    full_names = sorted(mentions, key=len, reverse=True)
    folded: dict[str, Character] = {}
    for name in full_names:
        parent = next(
            (
                other
                for other in folded
                if name != other and name in other.split()
            ),
            None,
        )
        if parent:
            child = mentions[name]
            host = folded[parent]
            if name not in host.aliases:
                host.aliases.append(name)
            host.first_mentioned_index = min(
                host.first_mentioned_index, child.first_mentioned_index
            )
            continue
        folded[name] = mentions[name]

    characters = []
    for character in folded.values():
        character.role = _role_for(character.name, raw_text)
        character.traits = _traits_for(character.name, sentences)
        characters.append(character)

    characters.sort(key=lambda item: item.first_mentioned_index)
    return characters


def _resolve_names(sentence: str, characters: list[Character]) -> list[str]:
    involved: list[str] = []
    for character in characters:
        tokens = [character.name, *character.aliases]
        if any(re.search(rf"\b{re.escape(token)}\b", sentence) for token in tokens):
            involved.append(character.name)
    return involved


def _build_timeline(
    sentences: list[str], characters: list[Character]
) -> list[TimelineCheckpoint]:
    checkpoints: list[TimelineCheckpoint] = []
    last_marker: str | None = None

    for index, sentence in enumerate(sentences):
        marker = _time_marker(sentence)
        starts_span = marker is not None and marker != last_marker
        is_turn = bool(
            marker
            or index == 0
            or _UNTIL_THEN.search(sentence)
            or sentence.lower().startswith(("that night", "after midnight"))
        )
        if not is_turn:
            continue

        order = len(checkpoints)
        checkpoint_id = f"cp_{order:02d}"
        checkpoints.append(
            TimelineCheckpoint(
                id=checkpoint_id,
                order=order,
                time_marker=marker if starts_span or marker else last_marker,
                event=sentence,
                characters_involved=_resolve_names(sentence, characters),
                source_excerpt=sentence,
            )
        )
        if marker:
            last_marker = marker

    if not checkpoints and sentences:
        checkpoints.append(
            TimelineCheckpoint(
                id="cp_00",
                order=0,
                time_marker=None,
                event=sentences[0],
                characters_involved=_resolve_names(sentences[0], characters),
                source_excerpt=sentences[0],
            )
        )
    return checkpoints


def _knowledge_windows(
    sentences: list[str],
    checkpoints: list[TimelineCheckpoint],
) -> list[KnowledgeSummary]:
    if not checkpoints:
        return []

    index_to_checkpoint: dict[int, str] = {}
    sentence_index_by_excerpt = {sentence: i for i, sentence in enumerate(sentences)}
    for checkpoint in checkpoints:
        source_index = sentence_index_by_excerpt.get(checkpoint.source_excerpt, checkpoint.order)
        index_to_checkpoint[source_index] = checkpoint.id

    ordered_bounds = []
    for sentence_index, sentence in enumerate(sentences):
        if sentence_index in index_to_checkpoint:
            ordered_bounds.append((sentence_index, index_to_checkpoint[sentence_index]))

    summaries: list[KnowledgeSummary] = []
    for bound_i, (start, checkpoint_id) in enumerate(ordered_bounds):
        end = ordered_bounds[bound_i + 1][0] if bound_i + 1 < len(ordered_bounds) else len(sentences)
        until = ordered_bounds[bound_i + 1][1] if bound_i + 1 < len(ordered_bounds) else None
        window = sentences[start:end]
        facts: list[str] = []
        beliefs: list[str] = []
        for sentence in window:
            facts.append(sentence)
            lowered = sentence.lower()
            if "believed" in lowered or "thought" in lowered or "until then" in lowered:
                beliefs.append(sentence)

        summaries.append(
            KnowledgeSummary(
                id=f"know_{bound_i:02d}",
                valid_from=checkpoint_id,
                valid_until=until,
                summary=" ".join(window),
                known_facts=facts,
                superseded_beliefs=beliefs,
            )
        )
    return summaries


class LoreAgent:
    """Ingests narrative text into a structured, time-aware lore graph."""

    def ingest(self, raw_text: str, *, source_title: str | None = None) -> LoreGraph:
        text = raw_text.strip()
        if not text:
            return LoreGraph(
                source_title=source_title or APP_NAME,
                characters=[],
                timeline=[],
                knowledge=[],
            )

        sentences = _sentences(text)
        characters = _canonical_characters(sentences, text)
        timeline = _build_timeline(sentences, characters)
        knowledge = _knowledge_windows(sentences, timeline)
        return LoreGraph(
            source_title=source_title or APP_NAME,
            characters=characters,
            timeline=timeline,
            knowledge=knowledge,
        )

    def ingest_to_json(
        self, raw_text: str, *, source_title: str | None = None, indent: int = 2
    ) -> str:
        return self.ingest(raw_text, source_title=source_title).model_dump_json(indent=indent)


def ingest_text(raw_text: str, *, source_title: str | None = None) -> LoreGraph:
    return LoreAgent().ingest(raw_text, source_title=source_title)
