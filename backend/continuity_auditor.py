"""Continuity auditor: spoiler leaks, temporal violations, one repair retry."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from interview_agent import _confusion_for, _ngrams, _tokens
from narrative_context import NarrativeContext

MAX_REPAIR_RETRIES = 1

_FOURTH_WALL = re.compile(
    r"\b(checkpoint|lore graph|fourth wall|as an ai|language model|"
    r"this story|the reader|the player|narrative engine|orchestrator|"
    r"cp_\d+|knowledge slice)\b",
    re.I,
)

ViolationKind = Literal[
    "spoiler_leak",
    "temporal_knowledge",
    "fourth_wall",
    "canon_contradiction",
    "character_voice",
    "supporting_inconsistency",
    "invented_conflict",
    "tonal_drift",
    "meta_language",
]


class Violation(BaseModel):
    kind: ViolationKind
    excerpt: str
    detail: str
    source_checkpoint: str | None = None


class AuditReport(BaseModel):
    passed: bool
    violations: list[Violation] = Field(default_factory=list)
    critique: str = ""

    def summarize(self) -> str:
        if self.passed:
            return "Continuity holds. No spoiler leaks or temporal violations."
        lines = [f"- [{item.kind}] {item.detail} Excerpt: {item.excerpt!r}" for item in self.violations]
        return "Continuity failed:\n" + "\n".join(lines)


class AuditCycle(BaseModel):
    output: str
    report: AuditReport
    retries: int = 0
    history: list[AuditReport] = Field(default_factory=list)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def future_only_ngrams(context: NarrativeContext) -> set[str]:
    known = _ngrams(" ".join(context.known_facts), sizes=(2, 3, 4, 5))
    future = _ngrams(" ".join(context.future_facts), sizes=(2, 3, 4, 5))
    return future - known


def future_only_tokens(context: NarrativeContext) -> set[str]:
    boring = {
        "the",
        "and",
        "that",
        "with",
        "from",
        "have",
        "been",
        "were",
        "this",
        "they",
        "them",
        "she",
        "her",
        "his",
        "had",
        "was",
        "for",
        "not",
        "only",
        "what",
        "had",
        "left",
    }
    known = _tokens(" ".join(context.known_facts))
    future = _tokens(" ".join(context.future_facts))
    return {token for token in (future - known) if len(token) >= 5 and token not in boring}


_META_LANGUAGE = re.compile(
    r"\b(in this story|the narrative|the author|the protagonist|"
    r"character arc|plot point|story arc|foreshadowing|backstory|"
    r"the tale|dear reader|gentle reader)\b",
    re.I,
)

_TONAL_DRIFT = re.compile(
    r"\b(lol|omg|basically|literally|awesome|super cool|dude|bro|"
    r"gonna|wanna|kinda|sorta|gotta|y'all|nah|yep|nope|haha)\b",
    re.I,
)


class ContinuityAuditor:
    """Judges generated prose against the character's legal knowledge window."""

    def audit(self, text: str, context: NarrativeContext) -> AuditReport:
        violations: list[Violation] = []
        lowered = text.lower()

        for match in _FOURTH_WALL.finditer(text):
            violations.append(
                Violation(
                    kind="fourth_wall",
                    excerpt=match.group(0),
                    detail="Output broke the fourth wall or named engine machinery.",
                )
            )

        for gram in sorted(future_only_ngrams(context), key=len, reverse=True):
            if gram in lowered:
                violations.append(
                    Violation(
                        kind="spoiler_leak",
                        excerpt=gram,
                        detail="Phrase belongs to a later checkpoint than the speaker inhabits.",
                        source_checkpoint=self._source_for(gram, context),
                    )
                )

        for token in sorted(future_only_tokens(context), key=len, reverse=True):
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                if any(token in item.excerpt for item in violations):
                    continue
                violations.append(
                    Violation(
                        kind="temporal_knowledge",
                        excerpt=token,
                        detail="Token is attested only after the active checkpoint.",
                        source_checkpoint=self._source_for(token, context),
                    )
                )

        # Keep longest excerpts; drop n-grams that overlap an already-kept leak.
        stop = {"the", "and", "to", "of", "a", "an", "in"}

        def content_words(excerpt: str) -> set[str]:
            return {word for word in excerpt.split() if word not in stop}

        compact: list[Violation] = []
        for item in sorted(violations, key=lambda row: len(row.excerpt), reverse=True):
            excerpt_words = set(item.excerpt.split())
            excerpt_content = content_words(item.excerpt)
            duplicate = False
            for prior in compact:
                prior_words = set(prior.excerpt.split())
                prior_content = content_words(prior.excerpt)
                if (
                    item.excerpt in prior.excerpt
                    or prior.excerpt in item.excerpt
                    or len(excerpt_words & prior_words) >= 2
                    or (excerpt_content and excerpt_content <= prior_content)
                ):
                    duplicate = True
                    break
            if not duplicate:
                compact.append(item)

        report = AuditReport(passed=not compact, violations=compact)
        report.critique = report.summarize()
        if not report.passed:
            report.critique += (
                " Repair: strip every leaking sentence. Speak only facts whose "
                f"valid_from is at or before {context.checkpoint_id}. If asked about "
                "later events, answer with in-character ignorance. Never name "
                "checkpoints or the engine."
            )
        return report

    def _source_for(self, needle: str, context: NarrativeContext) -> str | None:
        for summary in context.graph.knowledge:
            blob = " ".join([summary.summary, *summary.known_facts]).lower()
            if needle.lower() in blob:
                return summary.valid_from
        return None

    def repair(self, text: str, report: AuditReport, context: NarrativeContext) -> str:
        if report.passed:
            return text

        forbidden = [item.excerpt.lower() for item in report.violations]
        kept: list[str] = []
        for sentence in _sentences(text):
            lowered = sentence.lower()
            if _FOURTH_WALL.search(sentence):
                continue
            if any(excerpt in lowered for excerpt in forbidden):
                continue
            kept.append(sentence)

        cleaned = " ".join(kept).strip()
        leak_was_leave = any(
            "leave" in item.excerpt.lower()
            or "inland" in item.excerpt.lower()
            or "midnight" in item.excerpt.lower()
            for item in report.violations
        )
        if not cleaned or leak_was_leave:
            return _confusion_for(context.character, "Did you leave the lighthouse?")
        return cleaned

    def audit_spinoff(
        self,
        text: str,
        context: NarrativeContext,
    ) -> AuditReport:
        """Spinoff-specific audit: canon, voice, tone, meta language."""
        violations: list[Violation] = []
        lowered = text.lower()

        # Fourth wall (reuse existing pattern)
        for match in _FOURTH_WALL.finditer(text):
            violations.append(
                Violation(
                    kind="fourth_wall",
                    excerpt=match.group(0),
                    detail="Output broke the fourth wall or named engine machinery.",
                )
            )

        # Meta language
        for match in _META_LANGUAGE.finditer(text):
            violations.append(
                Violation(
                    kind="meta_language",
                    excerpt=match.group(0),
                    detail="Output used meta-narrative or AI language.",
                )
            )

        # Canon contradiction: check if the text contradicts known facts
        # by asserting the negation of a known fact
        for fact in context.known_facts:
            fact_lower = fact.lower()
            # Check for explicit negation of canon facts
            key_phrases = [p.strip() for p in fact_lower.split(".") if len(p.strip()) > 15]
            for phrase in key_phrases:
                negation_patterns = [
                    f"never {phrase[:30]}",
                    f"did not {phrase[:30]}",
                    f"had not {phrase[:30]}",
                    f"was not {phrase[:30]}",
                ]
                for neg in negation_patterns:
                    neg_words = neg.split()[:5]
                    neg_snippet = " ".join(neg_words)
                    if neg_snippet in lowered and phrase[:20] not in neg_snippet:
                        # Avoid false positives: only flag if the negation actually
                        # contradicts, not just uses similar words
                        if any(w in fact_lower for w in neg_words[1:3]):
                            violations.append(
                                Violation(
                                    kind="canon_contradiction",
                                    excerpt=neg_snippet,
                                    detail=f"Contradicts canon fact: {fact[:80]}",
                                )
                            )

        # Character voice: check for traits being violated
        char = context.character
        if char.name.lower().startswith("mara"):
            # Mara is reserved, duty-bound, solitary
            cheerful_markers = re.findall(
                r"\b(laughed brightly|grinned|cheered|celebrated|partied|danced with joy)\b",
                lowered,
            )
            for marker in cheerful_markers:
                violations.append(
                    Violation(
                        kind="character_voice",
                        excerpt=marker,
                        detail=f"{char.name}'s voice is reserved and duty-bound; this feels out of character.",
                    )
                )
        elif char.name.lower().startswith("kellan"):
            # Kellan is purposeful, mission-driven
            lazy_markers = re.findall(
                r"\b(gave up|abandoned his mission|forgot why he came|wandered aimlessly)\b",
                lowered,
            )
            for marker in lazy_markers:
                violations.append(
                    Violation(
                        kind="character_voice",
                        excerpt=marker,
                        detail=f"{char.name} is mission-driven; this contradicts his established voice.",
                    )
                )

        # Supporting character inconsistency
        other_chars = [c for c in context.graph.characters if c.name != char.name]
        for other in other_chars:
            other_lower = other.name.lower()
            if other_lower in lowered:
                # Check for role violations
                if other.role and other.role.lower() not in lowered:
                    pass  # Not a violation if role isn't mentioned
                for trait in other.traits:
                    negated = f"{other.name.lower()} was not {trait.lower()}"
                    if negated in lowered:
                        violations.append(
                            Violation(
                                kind="supporting_inconsistency",
                                excerpt=negated[:60],
                                detail=f"{other.name} has trait '{trait}'; text contradicts it.",
                            )
                        )

        # Tonal drift
        for match in _TONAL_DRIFT.finditer(text):
            violations.append(
                Violation(
                    kind="tonal_drift",
                    excerpt=match.group(0),
                    detail="Tone shifted to casual/modern register inconsistent with source.",
                )
            )

        # Invented elements conflicting with canon
        # Check for the text claiming events that directly contradict timeline
        timeline_events_lower = [cp.event.lower() for cp in context.graph.timeline]
        contradiction_phrases = re.findall(
            r"(?:there was no|there were no|never existed|had never been a)\s+([\w\s]{5,30})",
            lowered,
        )
        for phrase in contradiction_phrases:
            phrase_clean = phrase.strip()
            for event in timeline_events_lower:
                # If the text denies something that actually happened
                overlap_words = set(phrase_clean.split()) & set(event.split())
                if len(overlap_words) >= 2:
                    violations.append(
                        Violation(
                            kind="invented_conflict",
                            excerpt=phrase_clean[:50],
                            detail=f"Denies something established in timeline: {event[:60]}",
                        )
                    )
                    break

        report = AuditReport(passed=not violations, violations=violations)
        if violations:
            report.critique = (
                "Spinoff audit failed:\n"
                + "\n".join(
                    f"- [{v.kind}] {v.detail} Excerpt: {v.excerpt!r}"
                    for v in violations
                )
                + "\n Repair: fix each violation while preserving the story's "
                "flow and the character's established voice."
            )
        else:
            report.critique = "Spinoff passes continuity and voice checks."
        return report

    def enforce(
        self,
        draft: str,
        context: NarrativeContext,
        *,
        regenerate: Callable[[AuditReport], str] | None = None,
        max_retries: int = MAX_REPAIR_RETRIES,
        agent_type: str = "default",
    ) -> AuditCycle:
        if agent_type == "spinoff":
            audit_fn = self.audit_spinoff
        else:
            audit_fn = self.audit
        first = audit_fn(draft, context)
        history = [first]
        output = draft
        retries = 0
        if not first.passed and max_retries > 0:
            retries = 1
            output = regenerate(first) if regenerate else self.repair(draft, first, context)
            second = audit_fn(output, context)
            history.append(second)
            return AuditCycle(output=output, report=second, retries=retries, history=history)
        return AuditCycle(output=output, report=first, retries=retries, history=history)
