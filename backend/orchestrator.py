"""Orchestrator for Loom's core agentic loop.

State machine:
  Ingestion -> Capability Routing -> Generation -> Continuity Audit -> UI Output
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from continuity_auditor import AuditCycle, AuditReport, ContinuityAuditor
from interview_agent import InterviewAgent, InterviewTurn
from lore_agent import LoreAgent, LoreGraph
from narrative_context import NarrativeContext, build_context, resolve_character
from perspective_agent import PerspectiveAgent, PerspectiveDraft
from spinoff_agent import SpinoffAgent, SpinoffDraft, SpinoffType, StoryLength

Capability = Literal["ingest", "interview", "perspective", "spinoff"]


class Stage(str, Enum):
    INGESTION = "ingestion"
    CAPABILITY_ROUTING = "capability_routing"
    GENERATION = "generation"
    CONTINUITY_AUDIT = "continuity_audit"
    UI_OUTPUT = "ui_output"


class OrchestratorRequest(BaseModel):
    capability: Capability
    raw_text: str | None = None
    source_title: str | None = None
    graph: LoreGraph | None = None
    character_id: str | None = None
    checkpoint_id: str | None = None
    question: str | None = None
    injected_draft: str | None = Field(
        default=None,
        description="Optional pre-generated prose used to exercise the auditor retry path.",
    )
    # Spin-off parameters
    spinoff_type: SpinoffType | None = None
    tone: str = ""
    length: StoryLength = "medium"
    focus_prompt: str = ""
    language: str = ""


class UIOutput(BaseModel):
    stage: Stage = Stage.UI_OUTPUT
    capability: Capability
    text: str
    passed: bool
    retries: int = 0
    trace: list[str] = Field(default_factory=list)
    critique: str = ""
    interview: InterviewTurn | None = None
    perspective: PerspectiveDraft | None = None
    spinoff: SpinoffDraft | None = None
    graph: LoreGraph | None = None
    audit: AuditReport | None = None


class Orchestrator:
    def __init__(self) -> None:
        self.lore = LoreAgent()
        self.interview = InterviewAgent()
        self.perspective = PerspectiveAgent()
        self.spinoff = SpinoffAgent()
        self.auditor = ContinuityAuditor()

    def run(self, request: OrchestratorRequest) -> UIOutput:
        trace: list[str] = []

        trace.append(Stage.INGESTION.value)
        graph = request.graph
        if graph is None:
            if not request.raw_text:
                raise ValueError("Ingestion requires raw_text or a prebuilt lore graph.")
            graph = self.lore.ingest(request.raw_text, source_title=request.source_title)

        trace.append(Stage.CAPABILITY_ROUTING.value)
        if request.capability == "ingest":
            trace.append(Stage.UI_OUTPUT.value)
            return UIOutput(
                capability="ingest",
                text=graph.model_dump_json(indent=2),
                passed=True,
                trace=trace,
                graph=graph,
            )

        # Spin-off does not require a checkpoint
        if request.capability == "spinoff":
            if not request.character_id or not request.spinoff_type:
                raise ValueError("Spinoff requires character_id and spinoff_type.")
            # Use the first checkpoint as a reference for context building
            ref_checkpoint = graph.timeline[-1].id if graph.timeline else "cp_00"
            context = build_context(graph, request.character_id, ref_checkpoint)

            trace.append(Stage.GENERATION.value)
            spinoff_draft: SpinoffDraft | None = None
            if request.injected_draft is not None:
                draft = request.injected_draft
            else:
                spinoff_draft = self.spinoff.generate(
                    graph,
                    request.character_id,
                    request.spinoff_type,
                    tone=request.tone,
                    length=request.length,
                    focus_prompt=request.focus_prompt,
                    language=request.language,
                )
                draft = spinoff_draft.story

            trace.append(Stage.CONTINUITY_AUDIT.value)
            cycle = self._audit_with_retry(
                draft, context, request, None, None, spinoff_draft,
            )
            if spinoff_draft is not None:
                spinoff_draft.story = cycle.output

            trace.append(Stage.UI_OUTPUT.value)
            return UIOutput(
                capability=request.capability,
                text=cycle.output,
                passed=cycle.report.passed,
                retries=cycle.retries,
                trace=trace,
                critique=cycle.report.critique,
                spinoff=spinoff_draft,
                graph=graph,
                audit=cycle.report,
            )

        if not request.character_id or not request.checkpoint_id:
            raise ValueError("Interview and perspective require character_id and checkpoint_id.")

        context = build_context(graph, request.character_id, request.checkpoint_id)

        trace.append(Stage.GENERATION.value)
        interview_turn: InterviewTurn | None = None
        perspective_draft: PerspectiveDraft | None = None
        if request.injected_draft is not None:
            draft = request.injected_draft
        elif request.capability == "interview":
            if not request.question:
                raise ValueError("Interview requires a question.")
            interview_turn = self.interview.respond(
                character=context.character,
                checkpoint=context.checkpoint,
                knowledge_slice=context.active_knowledge,
                question=request.question,
                context=context,
            )
            draft = interview_turn.answer
        elif request.capability == "perspective":
            perspective_draft = self.perspective.rewrite(context)
            draft = perspective_draft.prose
        else:
            raise ValueError(f"Unsupported capability: {request.capability}")

        trace.append(Stage.CONTINUITY_AUDIT.value)
        cycle = self._audit_with_retry(draft, context, request, interview_turn, perspective_draft)
        if interview_turn is not None:
            interview_turn.answer = cycle.output
        if perspective_draft is not None:
            perspective_draft.prose = cycle.output

        trace.append(Stage.UI_OUTPUT.value)
        return UIOutput(
            capability=request.capability,
            text=cycle.output,
            passed=cycle.report.passed,
            retries=cycle.retries,
            trace=trace,
            critique=cycle.report.critique,
            interview=interview_turn,
            perspective=perspective_draft,
            graph=graph,
            audit=cycle.report,
        )

    def _audit_with_retry(
        self,
        draft: str,
        context: NarrativeContext,
        request: OrchestratorRequest,
        interview_turn: InterviewTurn | None,
        perspective_draft: PerspectiveDraft | None,
        spinoff_draft: SpinoffDraft | None = None,
    ) -> AuditCycle:
        def regenerate(report: AuditReport) -> str:
            if request.injected_draft is not None:
                return self.auditor.repair(draft, report, context)
            if request.capability == "interview" and request.question:
                repaired_turn = self.interview.respond(
                    character=context.character,
                    checkpoint=context.checkpoint,
                    knowledge_slice=context.active_knowledge,
                    question=request.question,
                    context=context,
                )
                return repaired_turn.answer
            if request.capability == "perspective":
                return self.perspective.rewrite(context).prose
            if request.capability == "spinoff" and request.spinoff_type:
                repaired = self.spinoff.generate(
                    context.graph,
                    request.character_id or context.character_id,
                    request.spinoff_type,
                    tone=request.tone,
                    length=request.length,
                    focus_prompt=request.focus_prompt,
                    language=request.language,
                )
                return repaired.story
            return self.auditor.repair(draft, report, context)

        agent_type = "spinoff" if request.capability == "spinoff" else "default"
        return self.auditor.enforce(
            draft, context, regenerate=regenerate, agent_type=agent_type,
        )
