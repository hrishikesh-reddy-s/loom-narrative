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

ViolationKind = Literal["spoiler_leak", "temporal_knowledge", "fourth_wall"]


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

    def enforce(
        self,
        draft: str,
        context: NarrativeContext,
        *,
        regenerate: Callable[[AuditReport], str] | None = None,
        max_retries: int = MAX_REPAIR_RETRIES,
    ) -> AuditCycle:
        first = self.audit(draft, context)
        history = [first]
        output = draft
        retries = 0
        if not first.passed and max_retries > 0:
            retries = 1
            output = regenerate(first) if regenerate else self.repair(draft, first, context)
            second = self.audit(output, context)
            history.append(second)
            return AuditCycle(output=output, report=second, retries=retries, history=history)
        return AuditCycle(output=output, report=first, retries=retries, history=history)
