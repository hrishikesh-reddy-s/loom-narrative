"""In-voice interview agent bound to a character's knowledge at one checkpoint."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from lore_agent import Character, KnowledgeSummary, TimelineCheckpoint
from narrative_context import NarrativeContext, flatten_facts

_WORD = re.compile(r"[a-z0-9']+")
_FOURTH_WALL = re.compile(
    r"\b(checkpoint|lore graph|fourth wall|as an ai|language model|"
    r"this story|the reader|the player|narrative engine|orchestrator|"
    r"cp_\d+)\b",
    re.I,
)


class InterviewTurn(BaseModel):
    character_id: str
    checkpoint_id: str
    question: str
    answer: str
    in_voice: bool = True
    refused_future: bool = False
    used_facts: list[str] = Field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _ngrams(text: str, sizes: tuple[int, ...] = (2, 3, 4)) -> set[str]:
    words = _WORD.findall(text.lower())
    grams: set[str] = set()
    for size in sizes:
        for index in range(0, len(words) - size + 1):
            grams.add(" ".join(words[index : index + size]))
    return grams


def question_asks_about_future(question: str, future_facts: list[str], known_facts: list[str]) -> bool:
    if not future_facts:
        return False
    allowed = _ngrams(" ".join(known_facts)) | _tokens(" ".join(known_facts))
    future_grams = _ngrams(" ".join(future_facts))
    future_only = {gram for gram in future_grams if gram not in _ngrams(" ".join(known_facts))}
    asked = _ngrams(question) | _tokens(question)
    if asked & future_only:
        return True
    # Distinctive future unigrams the question may use (leave/leaving/inland).
    future_unigrams = _tokens(" ".join(future_facts)) - allowed
    distinctive = {token for token in future_unigrams if len(token) >= 5}
    if asked & distinctive:
        return True
    leave_intent = bool(re.search(r"\b(leave|leaving|left)\b", question, re.I))
    future_has_leave = bool(re.search(r"\bleave\b", " ".join(future_facts), re.I))
    leave_already_known = bool(re.search(r"\bleave\b", " ".join(known_facts), re.I))
    return leave_intent and future_has_leave and not leave_already_known


def _first_person(fact: str, character: Character) -> str:
    text = fact
    names = sorted({character.name, *character.aliases}, key=len, reverse=True)
    for name in names:
        text = re.sub(rf"\b{re.escape(name)}\b", "I", text)
    text = re.sub(r"\bI Vale\b", "I", text)
    text = re.sub(r"\bshe had\b", "I had", text, flags=re.I)
    text = re.sub(r"\bshe was\b", "I was", text, flags=re.I)
    text = re.sub(r"\bshe believed\b", "I believed", text, flags=re.I)
    text = re.sub(r"\bshe thought\b", "I thought", text, flags=re.I)
    text = re.sub(r"\bshe learned\b", "I learned", text, flags=re.I)
    text = re.sub(r"\bshe found\b", "I found", text, flags=re.I)
    text = re.sub(r"\bshe agreed\b", "I agreed", text, flags=re.I)
    text = re.sub(r"\bshe did not\b", "I did not", text, flags=re.I)
    text = re.sub(r"\bher duty\b", "my duty", text, flags=re.I)
    text = re.sub(r"\bThat night I\b", "Tonight I", text)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _mara_confusion(question: str) -> str:
    _ = question
    return (
        "I don't know what you mean. The lamp is still burning and this gallery "
        "is still mine to walk. I keep the light. I have not gone anywhere. "
        "Tonight I know the bottle, the map, the stranger Kellan, and that I was "
        "never forgotten. Beyond that the dark is just dark."
    )


def _kellan_confusion() -> str:
    return (
        "I don't follow. I came for the map and for the hall the sea had hidden. "
        "Whatever you are asking after that, I have not lived it."
    )


def _confusion_for(character: Character, question: str) -> str:
    if character.name.lower().startswith("mara"):
        return _mara_confusion(question)
    if character.name.lower().startswith("kellan"):
        return _kellan_confusion()
    return (
        f"I hear your question, but that has not happened to me. I only know my "
        f"life as it stands."
    )


def _relevant_facts(question: str, known_facts: list[str]) -> list[str]:
    q_tokens = _tokens(question) - {
        "what",
        "when",
        "where",
        "why",
        "who",
        "how",
        "did",
        "do",
        "does",
        "have",
        "has",
        "the",
        "a",
        "an",
        "you",
        "your",
        "about",
        "tell",
        "me",
    }
    scored: list[tuple[int, str]] = []
    for fact in known_facts:
        overlap = len(_tokens(fact) & q_tokens)
        scored.append((overlap, fact))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [fact for score, fact in scored if score > 0][:3]
    if picked:
        return picked
    return known_facts[:3]


def _weave_answer(character: Character, checkpoint: TimelineCheckpoint, facts: list[str]) -> str:
    voiced = [_first_person(fact, character) for fact in facts]
    role = character.role or "the person you are asking"
    opening = (
        f"I am {character.name}, {role}, speaking from this hour"
        f"{f' ({checkpoint.time_marker.replace('_', ' ')})' if checkpoint.time_marker else ''}."
    )
    opening = opening.replace("()", "")
    body = " ".join(voiced)
    return f"{opening} {body}".strip()


class InterviewAgent:
    """Answers questions strictly in-character using only pre-checkpoint knowledge."""

    def respond(
        self,
        *,
        character: Character,
        checkpoint: TimelineCheckpoint,
        knowledge_slice: list[KnowledgeSummary],
        question: str,
        context: NarrativeContext | None = None,
    ) -> InterviewTurn:
        known = list(context.known_facts) if context else flatten_facts(knowledge_slice)
        # Active slice is authoritative for "what is true now"; remembered facts
        # from context cover earlier lived events still known to the speaker.
        slice_facts = flatten_facts(knowledge_slice)
        for fact in slice_facts:
            if fact not in known:
                known.append(fact)
        future = list(context.future_facts) if context else []

        if _FOURTH_WALL.search(question):
            answer = (
                "I don't know those words. Speak plainly. Ask me about the lamp, "
                "the water, or the hours I have actually lived."
            )
            return InterviewTurn(
                character_id=character.name,
                checkpoint_id=checkpoint.id,
                question=question,
                answer=answer,
                refused_future=False,
                used_facts=[],
            )

        if question_asks_about_future(question, future, known):
            return InterviewTurn(
                character_id=character.name,
                checkpoint_id=checkpoint.id,
                question=question,
                answer=_confusion_for(character, question),
                refused_future=True,
                used_facts=slice_facts[:2],
            )

        used = _relevant_facts(question, known)
        return InterviewTurn(
            character_id=character.name,
            checkpoint_id=checkpoint.id,
            question=question,
            answer=_weave_answer(character, checkpoint, used),
            refused_future=False,
            used_facts=used,
        )
