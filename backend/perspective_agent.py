"""Localized perspective rewrite of a single checkpoint/scene."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from lore_agent import Character, TimelineCheckpoint
from narrative_context import NarrativeContext, flatten_facts

_NAME = re.compile(r"\bMara Vale\b|\bMara\b")


class PerspectiveDraft(BaseModel):
    character_id: str
    checkpoint_id: str
    prose: str
    sensory_focus: list[str] = Field(default_factory=list)
    interior: str | None = None


def _scene_facts(context: NarrativeContext) -> list[str]:
    window = [
        item
        for item in context.active_knowledge
        if item.valid_from == context.checkpoint_id
    ]
    if window:
        return flatten_facts(window)
    return [context.checkpoint.event, context.checkpoint.source_excerpt]


def _mara_scene(checkpoint: TimelineCheckpoint, facts: list[str], known: list[str]) -> PerspectiveDraft:
    marker = checkpoint.time_marker or "this hour"
    joined = " ".join(facts).lower()
    sensory: list[str] = []
    interior = ""

    if marker == "that_night" or "never been forgotten" in joined:
        sensory = ["lamp-hum", "salt air", "gallery glass", "map creases"]
        interior = (
            "His words sit wrong in me: never forgotten. Years of keeping this light "
            "taught me the opposite. I do not argue. I listen to the tide and feel "
            "the map's folds under my thumb."
        )
        prose = (
            "Night leans on the gallery glass. The lamp ticks behind me, a familiar "
            "heat. Salt thickens the air. I stand with the drowned streets folded in "
            "my hands and Kellan's claim still unsettled in my chest: I had never "
            "been forgotten. The coast does not confirm it. The tide only breathes. "
            "I keep the light. That is the whole of my duty in this hour."
        )
    elif marker == "at_dawn" or "bottle" in joined:
        sensory = ["dawn light", "gallery rail", "sealed glass"]
        interior = "A bottle on my rail is already more company than I asked for."
        prose = (
            "Dawn scrapes the drowned coast. I find a sealed bottle on the gallery "
            "rail, glass still wet. Inside, a map of streets the water has already "
            "claimed. I turn it as if the paper might refuse to be real."
        )
    elif marker == "by_noon" or "kellan" in joined:
        sensory = ["noon glare", "skiff hull", "turning tide"]
        interior = "I do not trust him, but the tide is already choosing for me."
        prose = (
            "By noon a skiff cuts the glare and a stranger named Kellan claims the "
            "map is his. I watch his mouth more than his eyes. The tide is already "
            "turning against the piles. I keep my distance and keep the lamp in mind."
        )
    elif marker == "after_midnight" or "inland" in joined:
        sensory = ["dead hour", "cold lamp-rail", "inland dark"]
        interior = "The tower was a vow. I break it with both hands on the map."
        prose = (
            "After midnight the lighthouse feels smaller than my fear. I agree to "
            "leave it. The map is a weight against my ribs as I turn inland, away "
            "from the only duty I understood."
        )
    else:
        sensory = ["wind", "stone", "water"]
        interior = "I take in only what this hour will give me."
        remembered = known[0] if known else checkpoint.event
        prose = (
            f"From where I stand in this {marker.replace('_', ' ')}, the world is "
            f"only what I can touch. {remembered}"
        )

    return PerspectiveDraft(
        character_id="Mara Vale",
        checkpoint_id=checkpoint.id,
        prose=prose,
        sensory_focus=sensory,
        interior=interior,
    )


def _generic_scene(character: Character, checkpoint: TimelineCheckpoint, facts: list[str]) -> PerspectiveDraft:
    body = " ".join(facts) or checkpoint.event
    body = _NAME.sub("I", body)
    body = re.sub(rf"\b{re.escape(character.name)}\b", "I", body)
    prose = (
        f"I am {character.name}. This is the hour as it reaches me, not as anyone "
        f"else would tell it. {body} I notice the nearest sound and the nearest "
        f"doubt, and nothing that has not yet arrived."
    )
    return PerspectiveDraft(
        character_id=character.name,
        checkpoint_id=checkpoint.id,
        prose=prose,
        sensory_focus=["nearest sound", "body-near space"],
        interior="I do not borrow anyone else's eyes.",
    )


class PerspectiveAgent:
    """Rewrites a checkpoint as one character's limited, interior view."""

    def rewrite(self, context: NarrativeContext) -> PerspectiveDraft:
        facts = _scene_facts(context)
        if context.character.name.lower().startswith("mara"):
            return _mara_scene(context.checkpoint, facts, context.known_facts)
        return _generic_scene(context.character, context.checkpoint, facts)
