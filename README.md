# Loom — Multi-Agent Narrative Engine

Loom is a multi-agent narrative engine that ingests a story, extracts structured lore (characters, timeline, time-bounded knowledge), and provides three interactive capabilities:

1. **Interactive Interview** — Ask any character a question at a specific checkpoint. They answer in-voice using only knowledge available at that point in the timeline, refusing to acknowledge future events.

2. **Perspective Shift** — Rewrite a checkpoint as one character's interior, sensory experience.

3. **Character Spin-off** — Generate a standalone short story set in a character's world: parallel events alongside the main plot, a prequel before the story begins, or an aftermath after the final event.

All outputs are checked by an independent **Continuity Auditor** that flags spoiler leaks, temporal violations, fourth-wall breaks, canon contradictions, character-voice inconsistencies, and meta language. A single-retry repair loop fixes flagged issues automatically.

## Architecture

```
Frontend (Vite + React + Tailwind 4)
    ↓ fetch /api/*
FastAPI (main.py)
    ↓
Orchestrator (orchestrator.py)
    ├── LoreAgent (lore_agent.py)         — heuristic ingestion
    ├── InterviewAgent (interview_agent.py) — in-voice Q&A
    ├── PerspectiveAgent (perspective_agent.py) — interior rewrite
    ├── SpinoffAgent (spinoff_agent.py)    — standalone story generator
    └── ContinuityAuditor (continuity_auditor.py) — audit + repair
```

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys (optional — current agents are heuristic)
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173` and proxies API calls to `http://127.0.0.1:8000`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/ingest` | Ingest story text (multipart, JSON, or raw) |
| `GET` | `/api/sample` | Load the built-in sample story |
| `POST` | `/api/interview` | In-voice character interview |
| `POST` | `/api/perspective` | Perspective shift rewrite |
| `POST` | `/api/projects/{id}/spinoff` | **Character spin-off** |

### Spin-off Endpoint

**`POST /api/projects/{id}/spinoff`**

Request:
```json
{
  "character_id": "mara-vale",
  "spinoff_type": "parallel",
  "tone": "Match the source",
  "length": "medium",
  "focus_prompt": "",
  "language": ""
}
```

- `spinoff_type`: `"parallel"` | `"prequel"` | `"aftermath"`
- `length`: `"short"` (~500 words) | `"medium"` (~1000 words) | `"long"` (~2000 words)
- `tone` and `focus_prompt` are optional creative direction
- `language` is optional; blank = write in the source language

Response:
```json
{
  "title": "Meanwhile: Mara Vale and the Hours Between",
  "story": "The hours between the known events...",
  "canon_anchors": [
    { "event_id": "cp_00", "event_title": "Mara Vale kept the last lighthouse...", "how_used": "..." }
  ],
  "invented_elements": ["The lamp-winding ritual at first light", "..."],
  "audit": "Spinoff passes continuity and voice checks.",
  "trace": ["ingestion", "capability_routing", "generation", "continuity_audit", "ui_output"]
}
```

## Frontend Tabs

| Tab | Description |
|-----|-------------|
| **Interactive interview** | Chat with a character at a specific checkpoint |
| **Perspective shift** | Rewrite a checkpoint through one character's senses |
| **Character spin-off** | Generate a standalone story (parallel / prequel / aftermath) |

The checkpoint slider applies to interview and perspective tabs. On the spin-off tab, it's hidden since spin-offs span the full timeline.

## Running Tests

```bash
cd backend

# Existing tests (interview, perspective, auditor repair)
python test_agents.py

# Ingestion test
python test_ingestion.py

# Spin-off tests (schema, grounding, routing, auditor)
python test_spinoff.py
```

## Running the Spin-off Repair Demo

```bash
cd backend
python scripts/demo_spinoff_repair.py
```

This demonstrates the fault-injection repair loop:
1. A deliberately bad spin-off is injected (meta language, tonal drift, character-voice violations)
2. The auditor flags all violations
3. One repair retry runs
4. The repaired text passes the auditor

## Sample Story

The built-in sample is a short story about Mara Vale, a lighthouse keeper on a drowned coast, and Kellan, an archive envoy. Load it via the "Load sample story" button or `GET /api/sample`.
