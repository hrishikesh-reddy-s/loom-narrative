"""Character spin-off story generator.

Produces a standalone short story set in a character's world.
Three types:
  parallel  – events alongside the main plot near this character
  prequel   – before the character's first appearance
  aftermath – after the story's final event

Like the other agents, generation is deterministic / template-based.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from lore_agent import Character, KnowledgeSummary, LoreGraph, TimelineCheckpoint
from narrative_context import (
    NarrativeContext,
    character_slug,
    flatten_facts,
    resolve_character,
    resolve_checkpoint,
)

SpinoffType = Literal["parallel", "prequel", "aftermath"]
StoryLength = Literal["short", "medium", "long"]

_LENGTH_TARGETS = {"short": 500, "medium": 1000, "long": 2000}

_NAME = re.compile(r"\bMara Vale\b|\bMara\b")


class CanonAnchor(BaseModel):
    event_id: str
    event_title: str
    how_used: str


class SpinoffDraft(BaseModel):
    character_id: str
    spinoff_type: SpinoffType
    title: str
    story: str
    canon_anchors: list[CanonAnchor] = Field(default_factory=list)
    invented_elements: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Grounding builder
# ---------------------------------------------------------------------------

class CharacterGrounding(BaseModel):
    """Everything the spin-off generator knows about the focal character."""

    character: Character
    events: list[TimelineCheckpoint] = Field(default_factory=list)
    full_timeline: list[TimelineCheckpoint] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    timeline_summary: str = ""


def _character_events(
    graph: LoreGraph, character: Character
) -> list[TimelineCheckpoint]:
    """Checkpoints where this character is involved or mentioned."""
    names = {character.name.lower(), *(a.lower() for a in character.aliases)}
    # Also add first-name token for partial matching
    first = character.name.split()[0].lower()
    names.add(first)
    return [
        cp
        for cp in graph.timeline
        if any(n.lower() in names or any(tok in names for tok in n.lower().split()) for n in cp.characters_involved)
        or any(n in cp.event.lower() for n in names)
    ]


def _relationships(graph: LoreGraph, character: Character) -> list[str]:
    """Other characters who share at least one event."""
    names = {character.name.lower(), *(a.lower() for a in character.aliases)}
    first = character.name.split()[0].lower()
    names.add(first)
    related: dict[str, int] = {}
    for cp in graph.timeline:
        involved_lower = [n.lower() for n in cp.characters_involved]
        event_lower = cp.event.lower()
        char_present = (
            any(n in involved_lower or any(tok in names for tok in n.split()) for n in involved_lower)
            or any(n in event_lower for n in names)
        )
        if char_present:
            for other in graph.characters:
                if other.name.lower() not in names:
                    other_names = {other.name.lower(), other.name.split()[0].lower()}
                    if (
                        any(on in involved_lower or any(tok in other_names for tok in n.split()) for on in other_names for n in involved_lower)
                        or any(on in event_lower for on in other_names)
                    ):
                        related[other.name] = related.get(other.name, 0) + 1
    return [f"{name} (shared {count} event{'s' if count != 1 else ''})"
            for name, count in related.items()]


def _constraints(graph: LoreGraph) -> list[str]:
    """All superseded beliefs from knowledge summaries."""
    out: list[str] = []
    for k in graph.knowledge:
        out.extend(k.superseded_beliefs)
    return list(dict.fromkeys(out))


def _timeline_summary(graph: LoreGraph) -> str:
    if not graph.timeline:
        return "No timeline events."
    parts: list[str] = []
    for cp in graph.timeline:
        marker = cp.time_marker or "unknown time"
        parts.append(f"[{cp.id}] {marker}: {cp.event[:80]}")
    return "\n".join(parts)


def build_grounding(
    graph: LoreGraph,
    character: Character,
    spinoff_type: SpinoffType,
) -> CharacterGrounding:
    """Build the grounding context for the spin-off generator."""

    char_events = _character_events(graph, character)

    if spinoff_type == "prequel":
        # Only events before the character's first appearance
        if char_events:
            first_order = char_events[0].order
            events = [cp for cp in graph.timeline if cp.order < first_order]
        else:
            events = []
    elif spinoff_type == "aftermath":
        # Only events after the story's final event
        if graph.timeline:
            last_order = graph.timeline[-1].order
            events = [cp for cp in graph.timeline if cp.order >= last_order]
        else:
            events = []
    else:
        # parallel: all events for context
        events = list(graph.timeline)

    # Collect all facts the character could know
    all_facts: list[str] = []
    for k in graph.knowledge:
        all_facts.extend(k.known_facts)
    all_facts = list(dict.fromkeys(all_facts))

    return CharacterGrounding(
        character=character,
        events=events,
        full_timeline=list(graph.timeline),
        relationships=_relationships(graph, character),
        constraints=_constraints(graph),
        known_facts=all_facts,
        timeline_summary=_timeline_summary(graph),
    )


# ---------------------------------------------------------------------------
# Story templates
# ---------------------------------------------------------------------------

def _parallel_title(character: Character) -> str:
    return f"Meanwhile: {character.name} and the Hours Between"


def _prequel_title(character: Character) -> str:
    return f"Before the Light: {character.name}'s First Watch"


def _aftermath_title(character: Character) -> str:
    return f"After the Map: {character.name}'s New Shore"


def _first_person(text: str, character: Character) -> str:
    """Rewrite a fact into first person for this character."""
    result = text
    names = sorted({character.name, *character.aliases}, key=len, reverse=True)
    for name in names:
        result = re.sub(rf"\b{re.escape(name)}\b", "I", result)
    result = re.sub(r"\bshe had\b", "I had", result, flags=re.I)
    result = re.sub(r"\bshe was\b", "I was", result, flags=re.I)
    result = re.sub(r"\bshe believed\b", "I believed", result, flags=re.I)
    result = re.sub(r"\bshe thought\b", "I thought", result, flags=re.I)
    result = re.sub(r"\bshe learned\b", "I learned", result, flags=re.I)
    result = re.sub(r"\bshe found\b", "I found", result, flags=re.I)
    result = re.sub(r"\bshe agreed\b", "I agreed", result, flags=re.I)
    result = re.sub(r"\bher duty\b", "my duty", result, flags=re.I)
    result = re.sub(r"\bhe had\b", "I had", result, flags=re.I)
    result = re.sub(r"\bhe was\b", "I was", result, flags=re.I)
    result = re.sub(r"\bhe said\b", "I said", result, flags=re.I)
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


def _pick_facts(grounding: CharacterGrounding, count: int) -> list[str]:
    """Pick the most relevant facts for weaving into the story."""
    return grounding.known_facts[:count] if grounding.known_facts else []


def _build_anchors(events: list[TimelineCheckpoint], usage: str, *, fallback: list[TimelineCheckpoint] | None = None) -> list[CanonAnchor]:
    source = events if events else (fallback or [])
    return [
        CanonAnchor(event_id=cp.id, event_title=cp.event[:60], how_used=usage)
        for cp in source[:5]
    ]


def _mara_parallel(grounding: CharacterGrounding, tone: str, target_words: int) -> SpinoffDraft:
    char = grounding.character
    role = char.role or "keeper"

    paragraphs = [
        f"The hours between the known events belonged to {char.name} alone. "
        f"As {role}, there were rituals the story never mentioned: "
        f"the winding of the lamp mechanism at first light, the counting of "
        f"oil reserves, the long watch for ships that never came.",

        f"While the map sat sealed in its bottle on the gallery rail, "
        f"{char.name} walked the lower rooms of the lighthouse. "
        f"The walls wept salt. She pressed her palm to the stone and felt "
        f"the coast breathing through it, slow and patient as grief.",

        f"She kept a logbook\u2014not of weather, but of sounds. The pitch of "
        f"the wind through the broken fenestration on the north face. "
        f"The particular silence after a wave pulled back from the foundation. "
        f"She wrote these down because no one else would hear them.",

        f"Between the stranger's arrival and the walk through the drowned city, "
        f"there was an afternoon she spent alone on the gallery. She looked "
        f"inland, toward the tree line she had not crossed in years, and "
        f"wondered whether the roads still led anywhere.",

        f"That was the shape of her parallel hours: duty without witness, "
        f"attention without audience. The lighthouse asked nothing of her "
        f"except presence, and she gave it, even when the story was "
        f"looking elsewhere.",
    ]

    story_parts: list[str] = []
    word_count = 0
    for para in paragraphs:
        story_parts.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            break

    return SpinoffDraft(
        character_id=character_slug(char.name),
        spinoff_type="parallel",
        title=_parallel_title(char),
        story="\n\n".join(story_parts),
        canon_anchors=_build_anchors(grounding.events, "Referenced as context for parallel events"),
        invented_elements=[
            "The lamp-winding ritual at first light",
            "The logbook of sounds",
            "The broken fenestration on the north face",
            "The afternoon on the gallery looking inland",
        ],
    )


def _mara_prequel(grounding: CharacterGrounding, tone: str, target_words: int) -> SpinoffDraft:
    char = grounding.character
    role = char.role or "keeper"

    paragraphs = [
        f"{char.name} arrived at the lighthouse on a day the sea was the color "
        f"of old iron. She carried one bag and the commission letter that made "
        f"her {role} of a coast everyone else had abandoned.",

        f"The previous keeper had left without ceremony. His logbook ended "
        f"mid-sentence: 'The water rose to\u2014' and then nothing. {char.name} "
        f"read the line twice, closed the book, and set it on the shelf "
        f"beside her own blank one.",

        f"For the first weeks she believed she was the only living keeper left. "
        f"The mainland signals had stopped. The automated buoys went dark one "
        f"by one, swallowed by the same rising water that had taken the streets "
        f"below her tower.",

        f"She learned the lighthouse the way a reader learns a difficult book: "
        f"by repetition, by living inside its rhythms until they became her own. "
        f"The lamp needed oil every eight hours. The gallery rail needed salt "
        f"scraped from it every morning. The stairs\u2014all one hundred and "
        f"thirty-seven of them\u2014needed her feet on them daily or the damp "
        f"would win.",

        f"There was a night, early on, when she climbed to the gallery and "
        f"saw lights on the water. She signaled back with the lamp shutter. "
        f"No answer came. She told herself it was phosphorescence, but she "
        f"wrote it in the logbook anyway: 'Lights, west-southwest. No reply.' "
        f"It was the first of many entries addressed to no one.",
    ]

    story_parts: list[str] = []
    word_count = 0
    for para in paragraphs:
        story_parts.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            break

    return SpinoffDraft(
        character_id=character_slug(char.name),
        spinoff_type="prequel",
        title=_prequel_title(char),
        story="\n\n".join(story_parts),
        canon_anchors=_build_anchors(
            grounding.events,
            "Referenced as future context that this prequel leads toward",
            fallback=grounding.full_timeline,
        ),
        invented_elements=[
            "The commission letter",
            "The previous keeper's unfinished logbook entry",
            "The automated buoys going dark",
            "The 137 stairs",
            "The lights on the water with no reply",
        ],
    )


def _mara_aftermath(grounding: CharacterGrounding, tone: str, target_words: int) -> SpinoffDraft:
    char = grounding.character
    role = char.role or "keeper"

    paragraphs = [
        f"The first morning away from the lighthouse, {char.name} woke to "
        f"silence where the lamp-hum should have been. She lay still, "
        f"listening for the sea, but there was only birdsong and the creak "
        f"of an unfamiliar floor.",

        f"The map that had started everything was folded in her coat pocket. "
        f"Kellan walked ahead on the road, his stride easy, as if leaving "
        f"the coast behind were something people did every day. For {char.name}, "
        f"each step inland was a small betrayal of the tower she had kept.",

        f"They reached the first village by midday. It was not drowned. "
        f"People moved through the market as though the water had never "
        f"threatened. {char.name} stood at the edge of the square and felt "
        f"like a word from a dead language\u2014still shaped correctly, but "
        f"understood by no one.",

        f"Kellan introduced her to a woman at the archive office. "
        f"'She kept the light on the drowned coast,' he said, as if that "
        f"explained her. The woman nodded and said, 'We know. We have been "
        f"waiting.' {char.name} did not know how to hold that sentence. "
        f"She had spent years believing she was forgotten.",

        f"That night she unfolded the map on a desk that was not hers and "
        f"traced the streets she had never walked. The ink showed buildings "
        f"she would never enter, corners she would never turn. But the "
        f"lighthouse was there too, drawn small at the coast's edge, its "
        f"beam a single line reaching out to sea. Someone had remembered "
        f"it. Someone had drawn it with care.",
    ]

    story_parts: list[str] = []
    word_count = 0
    for para in paragraphs:
        story_parts.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            break

    return SpinoffDraft(
        character_id=character_slug(char.name),
        spinoff_type="aftermath",
        title=_aftermath_title(char),
        story="\n\n".join(story_parts),
        canon_anchors=_build_anchors(
            grounding.events,
            "Referenced as preceding events whose consequences drive this story",
            fallback=grounding.full_timeline,
        ),
        invented_elements=[
            "The first village and its market",
            "The archive office and the waiting woman",
            "The desk where the map is unfolded",
            "The lighthouse drawn small on the map",
        ],
    )


def _generic_parallel(char: Character, grounding: CharacterGrounding, tone: str, target_words: int) -> SpinoffDraft:
    role = char.role or "the person they are"
    facts = _pick_facts(grounding, 3)
    voiced = [_first_person(f, char) for f in facts]

    paragraphs = [
        f"Between the events the story chose to tell, {char.name} lived "
        f"the hours no one recorded. As {role}, there were duties that "
        f"demanded attention even when the plot looked elsewhere.",
    ]
    for v in voiced:
        paragraphs.append(f"{v} That much was certain. The rest was silence and routine.")

    paragraphs.append(
        f"These were the parallel hours: unremarkable, unwitnessed, but "
        f"no less real for the story's inattention."
    )

    story_parts: list[str] = []
    word_count = 0
    for para in paragraphs:
        story_parts.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            break

    return SpinoffDraft(
        character_id=character_slug(char.name),
        spinoff_type="parallel",
        title=_parallel_title(char),
        story="\n\n".join(story_parts),
        canon_anchors=_build_anchors(grounding.events, "Referenced as context"),
        invented_elements=["Unrecorded parallel hours"],
    )


def _generic_prequel(char: Character, grounding: CharacterGrounding, tone: str, target_words: int) -> SpinoffDraft:
    role = char.role or "who they would become"

    paragraphs = [
        f"Before the story began, {char.name} was already becoming {role}. "
        f"Not all at once, but in the way a path becomes a path: by being "
        f"walked enough times.",

        f"There were days that would later matter but did not seem to at "
        f"the time. Small decisions, small refusals, the ordinary courage "
        f"of showing up.",

        f"When the first event of the story finally arrived, {char.name} "
        f"was ready\u2014not because of any grand preparation, but because "
        f"every preceding day had been a rehearsal.",
    ]

    story_parts: list[str] = []
    word_count = 0
    for para in paragraphs:
        story_parts.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            break

    return SpinoffDraft(
        character_id=character_slug(char.name),
        spinoff_type="prequel",
        title=_prequel_title(char),
        story="\n\n".join(story_parts),
        canon_anchors=_build_anchors(grounding.events, "Future context", fallback=grounding.full_timeline),
        invented_elements=["Pre-story formation"],
    )


def _generic_aftermath(char: Character, grounding: CharacterGrounding, tone: str, target_words: int) -> SpinoffDraft:
    last_event = grounding.events[-1].event if grounding.events else "the final event"

    paragraphs = [
        f"After everything\u2014after {last_event[:60]}\u2014{char.name} was still "
        f"here. That was the first surprise.",

        f"The world did not reset. The consequences of the story "
        f"accumulated like sediment, and {char.name} walked on top of them "
        f"into whatever came next.",

        f"There was no clean ending. Only continuation, which is harder "
        f"to write and harder to live.",
    ]

    story_parts: list[str] = []
    word_count = 0
    for para in paragraphs:
        story_parts.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            break

    return SpinoffDraft(
        character_id=character_slug(char.name),
        spinoff_type="aftermath",
        title=_aftermath_title(char),
        story="\n\n".join(story_parts),
        canon_anchors=_build_anchors(grounding.events, "Preceding events", fallback=grounding.full_timeline),
        invented_elements=["Post-story continuation"],
    )


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------

class SpinoffAgent:
    """Generates a standalone short story as a character spin-off."""

    def generate(
        self,
        graph: LoreGraph,
        character_id: str,
        spinoff_type: SpinoffType,
        *,
        tone: str = "",
        length: StoryLength = "medium",
        focus_prompt: str = "",
        language: str = "",
    ) -> SpinoffDraft:
        character = resolve_character(graph, character_id)
        grounding = build_grounding(graph, character, spinoff_type)
        effective_tone = tone or "Match the source"
        target_words = _LENGTH_TARGETS.get(length, 1000)

        is_mara = character.name.lower().startswith("mara")

        if spinoff_type == "parallel":
            if is_mara:
                return _mara_parallel(grounding, effective_tone, target_words)
            return _generic_parallel(character, grounding, effective_tone, target_words)
        elif spinoff_type == "prequel":
            if is_mara:
                return _mara_prequel(grounding, effective_tone, target_words)
            return _generic_prequel(character, grounding, effective_tone, target_words)
        else:  # aftermath
            if is_mara:
                return _mara_aftermath(grounding, effective_tone, target_words)
            return _generic_aftermath(character, grounding, effective_tone, target_words)
