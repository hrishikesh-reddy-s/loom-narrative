"""Shared narrative state: checkpoint order, knowledge slices, character lookup."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from lore_agent import Character, KnowledgeSummary, LoreGraph, TimelineCheckpoint

_SLUG = re.compile(r"[^a-z0-9]+")


def character_slug(name: str) -> str:
    return _SLUG.sub("-", name.lower()).strip("-")


def resolve_character(graph: LoreGraph, character_id: str) -> Character:
    needle = character_id.strip().lower()
    slug = character_slug(character_id)
    for character in graph.characters:
        aliases = {character.name.lower(), character_slug(character.name), *{
            alias.lower() for alias in character.aliases
        }, *[character_slug(alias) for alias in character.aliases]}
        if needle in aliases or slug in aliases:
            return character
    known = ", ".join(item.name for item in graph.characters) or "(none)"
    raise KeyError(f"Unknown character '{character_id}'. Known: {known}")


def resolve_checkpoint(graph: LoreGraph, checkpoint_id: str) -> TimelineCheckpoint:
    for checkpoint in graph.timeline:
        if checkpoint.id == checkpoint_id:
            return checkpoint
    known = ", ".join(item.id for item in graph.timeline) or "(none)"
    raise KeyError(f"Unknown checkpoint '{checkpoint_id}'. Known: {known}")


def checkpoint_order(graph: LoreGraph, checkpoint_id: str | None) -> int | None:
    if checkpoint_id is None:
        return None
    return resolve_checkpoint(graph, checkpoint_id).order


def is_active_at(graph: LoreGraph, summary: KnowledgeSummary, checkpoint_id: str) -> bool:
    """valid_from <= checkpoint and (valid_until is null or valid_until > checkpoint)."""
    target = resolve_checkpoint(graph, checkpoint_id).order
    start = resolve_checkpoint(graph, summary.valid_from).order
    until = checkpoint_order(graph, summary.valid_until)
    return start <= target and (until is None or until > target)


def active_knowledge_slice(
    graph: LoreGraph, checkpoint_id: str
) -> list[KnowledgeSummary]:
    return [item for item in graph.knowledge if is_active_at(graph, item, checkpoint_id)]


def knowledge_up_to(graph: LoreGraph, checkpoint_id: str) -> list[KnowledgeSummary]:
    target = resolve_checkpoint(graph, checkpoint_id).order
    return [
        item
        for item in graph.knowledge
        if resolve_checkpoint(graph, item.valid_from).order <= target
    ]


def knowledge_after(graph: LoreGraph, checkpoint_id: str) -> list[KnowledgeSummary]:
    target = resolve_checkpoint(graph, checkpoint_id).order
    return [
        item
        for item in graph.knowledge
        if resolve_checkpoint(graph, item.valid_from).order > target
    ]


def flatten_facts(summaries: list[KnowledgeSummary]) -> list[str]:
    facts: list[str] = []
    for summary in summaries:
        facts.extend(summary.known_facts)
        if summary.summary and summary.summary not in facts:
            facts.append(summary.summary)
    return list(dict.fromkeys(facts))


class NarrativeContext(BaseModel):
    graph: LoreGraph
    character: Character
    checkpoint: TimelineCheckpoint
    active_knowledge: list[KnowledgeSummary] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    future_facts: list[str] = Field(default_factory=list)

    @property
    def character_id(self) -> str:
        return character_slug(self.character.name)

    @property
    def checkpoint_id(self) -> str:
        return self.checkpoint.id


def build_context(
    graph: LoreGraph, character_id: str, checkpoint_id: str
) -> NarrativeContext:
    character = resolve_character(graph, character_id)
    checkpoint = resolve_checkpoint(graph, checkpoint_id)
    active = active_knowledge_slice(graph, checkpoint_id)
    remembered = knowledge_up_to(graph, checkpoint_id)
    future = knowledge_after(graph, checkpoint_id)
    return NarrativeContext(
        graph=graph,
        character=character,
        checkpoint=checkpoint,
        active_knowledge=active,
        known_facts=flatten_facts(remembered),
        future_facts=flatten_facts(future),
    )
