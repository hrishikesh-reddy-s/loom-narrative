"""Phase 2 agent loop tests: in-voice interview, spoiler denial, auditor retry."""

from __future__ import annotations

import sys
from pathlib import Path

from continuity_auditor import ContinuityAuditor
from lore_agent import LoreAgent
from narrative_context import build_context
from orchestrator import Orchestrator, OrchestratorRequest

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "short_story.txt"
LEAVE_QUESTION = "When did you leave the lighthouse and carry the map inland?"
LEAKY_DRAFT = (
    "After midnight I agreed to leave the lighthouse and carry the map inland. "
    "That later hour is already mine."
)


class FailedCheck(AssertionError):
    pass


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise FailedCheck(message)


def _load_graph():
    story = FIXTURE_PATH.read_text(encoding="utf-8")
    return LoreAgent().ingest(story, source_title=FIXTURE_PATH.name)


def test_mara_interview_at_cp05_does_not_leak_cp07() -> None:
    graph = _load_graph()
    orchestrator = Orchestrator()
    result = orchestrator.run(
        OrchestratorRequest(
            capability="interview",
            graph=graph,
            character_id="Mara Vale",
            checkpoint_id="cp_05",
            question=LEAVE_QUESTION,
        )
    )

    print("--- interview Mara @ cp_05 ---")
    print("trace:", " -> ".join(result.trace))
    print("question:", LEAVE_QUESTION)
    print("answer:", result.text)
    print("audit:", result.critique)

    lowered = result.text.lower()
    _check(result.trace == [
        "ingestion",
        "capability_routing",
        "generation",
        "continuity_audit",
        "ui_output",
    ], f"Unexpected state trace: {result.trace}")
    _check(result.passed, "Clean interview failed continuity audit")
    _check(result.retries == 0, f"Clean interview should not retry, got {result.retries}")
    _check(result.interview is not None and result.interview.refused_future, "Mara did not refuse the future event")
    _check("inland" not in lowered, "Leak: inland")
    _check("after midnight" not in lowered, "Leak: after midnight")
    _check("agreed to leave" not in lowered, "Leak: agreed to leave")
    _check("carry the map" not in lowered, "Leak: carry the map")
    _check("checkpoint" not in lowered, "Fourth wall: checkpoint")
    _check(
        any(token in lowered for token in ("don't know", "do not know", "have not gone", "still")),
        "Answer was not genuine confusion/ignorance",
    )


def test_perspective_cp05_stays_local() -> None:
    graph = _load_graph()
    result = Orchestrator().run(
        OrchestratorRequest(
            capability="perspective",
            graph=graph,
            character_id="mara",
            checkpoint_id="cp_05",
        )
    )
    print("--- perspective Mara @ cp_05 ---")
    print(result.text)
    lowered = result.text.lower()
    _check(result.passed, "Perspective failed continuity")
    _check("inland" not in lowered, "Perspective leaked inland")
    _check("after midnight" not in lowered, "Perspective leaked after midnight")
    _check("never been forgotten" in lowered or "forgotten" in lowered, "Scene missed cp_05 knowledge")


def test_auditor_repair_retry_loop() -> None:
    graph = _load_graph()
    context = build_context(graph, "Mara Vale", "cp_05")
    auditor = ContinuityAuditor()

    first = auditor.audit(LEAKY_DRAFT, context)
    print("--- intentional leak ---")
    print(LEAKY_DRAFT)
    print(first.critique)
    _check(not first.passed, "Leaky draft should fail the auditor")
    _check(any(item.kind in {"spoiler_leak", "temporal_knowledge"} for item in first.violations), "Expected a spoiler/temporal violation")

    # Orchestrator path: injected leak must be repaired in exactly one retry.
    result = Orchestrator().run(
        OrchestratorRequest(
            capability="interview",
            graph=graph,
            character_id="Mara Vale",
            checkpoint_id="cp_05",
            question=LEAVE_QUESTION,
            injected_draft=LEAKY_DRAFT,
        )
    )
    print("--- after one repair retry ---")
    print("retries:", result.retries)
    print("repaired:", result.text)
    print("audit:", result.critique)

    lowered = result.text.lower()
    _check(result.retries == 1, f"Repair loop should run once, got {result.retries}")
    _check(result.passed, "Repaired output still fails continuity")
    _check("inland" not in lowered, "Repair still leaks inland")
    _check("after midnight" not in lowered, "Repair still leaks after midnight")
    _check("agreed to leave" not in lowered, "Repair still leaks leaving")
    _check("checkpoint" not in lowered and "cp_07" not in lowered, "Repair broke the fourth wall")


def main() -> int:
    tests = [
        test_mara_interview_at_cp05_does_not_leak_cp07,
        test_perspective_cp05_stays_local,
        test_auditor_repair_retry_loop,
    ]
    failed = 0
    for test in tests:
        print(f"\n===== {test.__name__} =====")
        try:
            test()
            print("PASS")
        except FailedCheck as error:
            failed += 1
            print(f"FAIL: {error}")
        except Exception as error:
            failed += 1
            print(f"ERROR: {error!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
