"""Spin-off repair demo: fault-injection → auditor → repair → re-audit.

OFF by default. Run manually:
    cd backend && python scripts/demo_spinoff_repair.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from the backend directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from continuity_auditor import ContinuityAuditor
from lore_agent import LoreAgent
from narrative_context import build_context
from orchestrator import Orchestrator, OrchestratorRequest

FIXTURE_PATH = BACKEND_DIR / "fixtures" / "short_story.txt"

# A deliberately bad spin-off that contradicts canon and uses meta language.
FAULTY_SPINOFF = (
    "Mara laughed brightly and cheered as she danced around the lighthouse. "
    "In this story, she had always been happy and carefree, surrounded by "
    "friends who visited daily. LOL, lighthouse life was basically awesome! "
    "Dear reader, Mara's character arc was all about finding joy. "
    "Kellan had never existed—there was no stranger, no map, no bottle. "
    "The narrative was super cool and the protagonist loved every minute."
)


def main() -> None:
    story = FIXTURE_PATH.read_text(encoding="utf-8")
    graph = LoreAgent().ingest(story, source_title=FIXTURE_PATH.name)
    last_cp = graph.timeline[-1].id if graph.timeline else "cp_00"
    context = build_context(graph, "Mara Vale", last_cp)
    auditor = ContinuityAuditor()

    print("=" * 70)
    print("SPIN-OFF REPAIR DEMO (fault-injection)")
    print("=" * 70)

    # Step 1: Show the violating text
    print("\n--- 1. FAULTY SPIN-OFF ---")
    print(FAULTY_SPINOFF)

    # Step 2: Audit it
    print("\n--- 2. AUDITOR FINDINGS ---")
    report = auditor.audit_spinoff(FAULTY_SPINOFF, context)
    print(f"Passed: {report.passed}")
    print(f"Violations: {len(report.violations)}")
    for v in report.violations:
        print(f"  [{v.kind}] {v.excerpt!r} — {v.detail}")

    # Step 3: Repair instruction
    print("\n--- 3. REPAIR INSTRUCTION ---")
    print(report.critique)

    # Step 4: Run through orchestrator with injected draft (triggers repair loop)
    print("\n--- 4. ORCHESTRATOR REPAIR LOOP ---")
    orchestrator = Orchestrator()
    result = orchestrator.run(
        OrchestratorRequest(
            capability="spinoff",
            graph=graph,
            character_id="Mara Vale",
            spinoff_type="parallel",
            injected_draft=FAULTY_SPINOFF,
        )
    )

    print(f"Retries: {result.retries}")
    print(f"\n--- 5. REPAIRED TEXT ---")
    print(result.text)

    print(f"\n--- 6. FINAL AUDIT ---")
    print(f"Passed: {result.passed}")
    print(f"Critique: {result.critique}")
    print(f"Trace: {' -> '.join(result.trace)}")

    print("\n" + "=" * 70)
    if result.retries >= 1:
        print("DEMO SUCCESS: Fault was injected, auditor flagged it, repair ran.")
    else:
        print("DEMO NOTE: No repair was needed (auditor did not flag the injection).")
    print("=" * 70)


if __name__ == "__main__":
    main()
