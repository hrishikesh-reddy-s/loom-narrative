"""Spin-off capability tests: schema validation, grounding builder, orchestrator routing, auditor."""

from __future__ import annotations

import sys
from pathlib import Path

from continuity_auditor import ContinuityAuditor
from lore_agent import LoreAgent
from narrative_context import build_context
from orchestrator import Orchestrator, OrchestratorRequest
from spinoff_agent import (
    CanonAnchor,
    CharacterGrounding,
    SpinoffAgent,
    SpinoffDraft,
    build_grounding,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "short_story.txt"


class FailedCheck(AssertionError):
    pass


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise FailedCheck(message)


def _load_graph():
    story = FIXTURE_PATH.read_text(encoding="utf-8")
    return LoreAgent().ingest(story, source_title=FIXTURE_PATH.name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_spinoff_request_schema() -> None:
    """SpinoffDraft and CanonAnchor models accept valid input."""
    anchor = CanonAnchor(event_id="cp_00", event_title="Test event", how_used="Context")
    _check(anchor.event_id == "cp_00", "CanonAnchor construction failed")

    draft = SpinoffDraft(
        character_id="mara-vale",
        spinoff_type="parallel",
        title="Test",
        story="A short story.",
        canon_anchors=[anchor],
        invented_elements=["Something new"],
    )
    _check(draft.spinoff_type == "parallel", "SpinoffDraft type mismatch")
    _check(len(draft.canon_anchors) == 1, "SpinoffDraft anchors mismatch")
    _check(len(draft.invented_elements) == 1, "SpinoffDraft invented mismatch")

    # Reject invalid spinoff_type
    try:
        SpinoffDraft(
            character_id="mara-vale",
            spinoff_type="invalid",  # type: ignore[arg-type]
            title="Test",
            story="A short story.",
        )
        _check(False, "Should have rejected invalid spinoff_type")
    except Exception:
        pass  # Expected

    print("SpinoffDraft and CanonAnchor schemas validated")


def test_grounding_builder_parallel() -> None:
    """Parallel grounding includes all timeline events."""
    graph = _load_graph()
    from narrative_context import resolve_character
    mara = resolve_character(graph, "Mara Vale")
    grounding = build_grounding(graph, mara, "parallel")

    _check(len(grounding.events) == len(graph.timeline),
           f"Parallel should include all {len(graph.timeline)} events, got {len(grounding.events)}")
    _check(len(grounding.known_facts) > 0, "Grounding should have known facts")
    _check(len(grounding.relationships) > 0, "Grounding should have relationships")
    _check("Kellan" in grounding.relationships[0], f"Expected Kellan in relationships, got {grounding.relationships}")
    print(f"Parallel grounding: {len(grounding.events)} events, "
          f"{len(grounding.known_facts)} facts, {len(grounding.relationships)} relationships")


def test_grounding_builder_prequel() -> None:
    """Prequel grounding includes only events before the character's first appearance."""
    graph = _load_graph()
    from narrative_context import resolve_character
    kellan = resolve_character(graph, "Kellan")
    grounding = build_grounding(graph, kellan, "prequel")

    # Kellan first appears at some checkpoint; prequel events should be before that
    from spinoff_agent import _character_events
    kellan_events = _character_events(graph, kellan)
    first_order = kellan_events[0].order if kellan_events else 0

    for event in grounding.events:
        _check(event.order < first_order,
               f"Prequel event {event.id} (order {event.order}) is not before first appearance ({first_order})")
    print(f"Prequel grounding for Kellan: {len(grounding.events)} events before order {first_order}")


def test_grounding_builder_aftermath() -> None:
    """Aftermath grounding includes only events at or after the final checkpoint."""
    graph = _load_graph()
    from narrative_context import resolve_character
    mara = resolve_character(graph, "Mara Vale")
    grounding = build_grounding(graph, mara, "aftermath")

    last_order = graph.timeline[-1].order if graph.timeline else 0
    for event in grounding.events:
        _check(event.order >= last_order,
               f"Aftermath event {event.id} (order {event.order}) is before final ({last_order})")
    _check(len(grounding.events) >= 1, "Aftermath should include at least the final event")
    print(f"Aftermath grounding: {len(grounding.events)} events at or after order {last_order}")


def test_orchestrator_routes_spinoff() -> None:
    """Orchestrator returns a spinoff result with correct trace."""
    graph = _load_graph()
    orchestrator = Orchestrator()
    result = orchestrator.run(
        OrchestratorRequest(
            capability="spinoff",
            graph=graph,
            character_id="Mara Vale",
            spinoff_type="parallel",
            length="short",
        )
    )

    expected_trace = [
        "ingestion",
        "capability_routing",
        "generation",
        "continuity_audit",
        "ui_output",
    ]
    _check(result.trace == expected_trace, f"Unexpected trace: {result.trace}")
    _check(result.spinoff is not None, "Spinoff draft is None")
    _check(result.spinoff.spinoff_type == "parallel", f"Wrong spinoff type: {result.spinoff.spinoff_type}")
    _check(len(result.spinoff.title) > 0, "Spinoff title is empty")
    _check(len(result.text) > 100, f"Spinoff story too short: {len(result.text)} chars")
    _check(len(result.spinoff.canon_anchors) > 0, "No canon anchors")
    _check(len(result.spinoff.invented_elements) > 0, "No invented elements")
    _check(result.passed, f"Spinoff failed audit: {result.critique}")
    print(f"Orchestrator spinoff: '{result.spinoff.title}', "
          f"{len(result.text)} chars, {len(result.spinoff.canon_anchors)} anchors, "
          f"passed={result.passed}")


def test_spinoff_auditor_catches_contradiction() -> None:
    """Auditor catches canon violations in spinoff text."""
    graph = _load_graph()
    context = build_context(graph, "Mara Vale", graph.timeline[-1].id)
    auditor = ContinuityAuditor()

    # Text with meta language and tonal drift
    bad_text = (
        "In this story, Mara laughed brightly and cheered as she danced with joy. "
        "LOL, it was basically awesome! The narrative was super cool. "
        "Dear reader, the protagonist's character arc was amazing."
    )
    report = auditor.audit_spinoff(bad_text, context)
    print(f"Bad spinoff audit: passed={report.passed}, {len(report.violations)} violations")
    for v in report.violations:
        print(f"  - [{v.kind}] {v.excerpt!r}: {v.detail}")

    _check(not report.passed, "Bad spinoff text should fail audit")
    kinds = {v.kind for v in report.violations}
    _check("meta_language" in kinds, "Should catch meta language")
    _check("character_voice" in kinds, "Should catch character voice violation")
    _check("tonal_drift" in kinds, "Should catch tonal drift")

    # Clean text should pass
    clean_text = (
        "The hours between the known events belonged to Mara Vale alone. "
        "She walked the lower rooms of the lighthouse in silence."
    )
    clean_report = auditor.audit_spinoff(clean_text, context)
    _check(clean_report.passed, f"Clean spinoff text should pass: {clean_report.critique}")
    print(f"Clean spinoff audit: passed={clean_report.passed}")


def test_all_three_spinoff_types() -> None:
    """Generate one spinoff of each type and verify basic structure."""
    graph = _load_graph()
    agent = SpinoffAgent()

    for stype in ("parallel", "prequel", "aftermath"):
        draft = agent.generate(graph, "Mara Vale", stype, length="short")  # type: ignore[arg-type]
        _check(draft.spinoff_type == stype, f"Type mismatch: expected {stype}, got {draft.spinoff_type}")
        _check(len(draft.title) > 5, f"{stype}: title too short")
        _check(len(draft.story) > 50, f"{stype}: story too short ({len(draft.story)} chars)")
        _check(len(draft.canon_anchors) > 0, f"{stype}: no canon anchors")
        _check(len(draft.invented_elements) > 0, f"{stype}: no invented elements")
        print(f"  {stype}: '{draft.title}' ({len(draft.story)} chars, "
              f"{len(draft.canon_anchors)} anchors, {len(draft.invented_elements)} invented)")


def main() -> int:
    tests = [
        test_spinoff_request_schema,
        test_grounding_builder_parallel,
        test_grounding_builder_prequel,
        test_grounding_builder_aftermath,
        test_orchestrator_routes_spinoff,
        test_spinoff_auditor_catches_contradiction,
        test_all_three_spinoff_types,
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
