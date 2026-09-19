"""Loom FastAPI application: ingest, interview, perspective, sample demo."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from lore_agent import Character, KnowledgeSummary, LoreGraph, TimelineCheckpoint
from narrative_context import build_context, character_slug
from orchestrator import Orchestrator, OrchestratorRequest
from spinoff_agent import CanonAnchor, SpinoffDraft, SpinoffType, StoryLength

BACKEND_DIR = Path(__file__).resolve().parent
SAMPLE_STORY_PATH = BACKEND_DIR / "fixtures" / "short_story.txt"

app = FastAPI(title="Loom", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()


class SessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.raw_text: str | None = None
        self.graph: LoreGraph | None = None
        self.title: str | None = None

    def set(self, *, raw_text: str, graph: LoreGraph, title: str | None) -> None:
        with self._lock:
            self.raw_text = raw_text
            self.graph = graph
            self.title = title

    def snapshot(self) -> tuple[str | None, LoreGraph | None]:
        with self._lock:
            return self.raw_text, self.graph


store = SessionStore()


class CharacterOut(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: str | None = None
    traits: list[str] = Field(default_factory=list)


class CheckpointOut(BaseModel):
    id: str
    order: int
    time_marker: str | None = None
    event: str
    characters_involved: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: Literal["user", "character", "assistant"]
    content: str


class InterviewBody(BaseModel):
    character_id: str
    checkpoint_id: str
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class PerspectiveBody(BaseModel):
    character_id: str
    checkpoint_id: str


class SpinoffBody(BaseModel):
    character_id: str
    spinoff_type: SpinoffType
    tone: str = Field(default="", description="Tonal direction; blank = match the source.")
    length: StoryLength = "medium"
    focus_prompt: str = Field(default="", description="Optional creative prompt.")
    language: str = Field(default="", description="Target language; blank = source language.")


class CanonAnchorOut(BaseModel):
    event_id: str
    event_title: str
    how_used: str


class SpinoffResponse(BaseModel):
    title: str
    story: str
    canon_anchors: list[CanonAnchorOut]
    invented_elements: list[str]
    audit: str
    trace: list[str]


class StoryState(BaseModel):
    source_title: str
    story: str
    characters: list[CharacterOut]
    checkpoints: list[CheckpointOut]
    knowledge: list[KnowledgeSummary]


def _character_out(character: Character) -> CharacterOut:
    return CharacterOut(
        id=character_slug(character.name),
        name=character.name,
        aliases=character.aliases,
        role=character.role,
        traits=character.traits,
    )


def _checkpoint_out(checkpoint: TimelineCheckpoint) -> CheckpointOut:
    return CheckpointOut(
        id=checkpoint.id,
        order=checkpoint.order,
        time_marker=checkpoint.time_marker,
        event=checkpoint.event,
        characters_involved=checkpoint.characters_involved,
    )


def _story_state(raw_text: str, graph: LoreGraph) -> StoryState:
    return StoryState(
        source_title=graph.source_title,
        story=raw_text,
        characters=[_character_out(item) for item in graph.characters],
        checkpoints=[_checkpoint_out(item) for item in graph.timeline],
        knowledge=graph.knowledge,
    )


def _require_graph() -> tuple[str, LoreGraph]:
    raw_text, graph = store.snapshot()
    if graph is None or raw_text is None:
        raise HTTPException(
            status_code=409,
            detail="No story is loaded. Ingest text or load the sample first.",
        )
    return raw_text, graph


def _effective_question(message: str, history: list[ChatMessage]) -> str:
    stripped = message.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="message is required")
    if len(stripped.split()) > 3:
        return stripped
    last_user = next((item.content for item in reversed(history) if item.role == "user"), None)
    if last_user:
        return f"{last_user}\n{stripped}"
    return stripped


async def _read_ingest_payload(request: Request) -> tuple[str, str]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if isinstance(upload, StarletteUploadFile):
            payload = await upload.read()
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail="Uploaded file must be UTF-8 text.") from exc
            title = upload.filename or "upload.txt"
            if not text.strip():
                raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            return text, title
        pasted = form.get("text")
        if isinstance(pasted, str) and pasted.strip():
            return pasted, "paste.txt"
        raise HTTPException(status_code=400, detail="Provide a .txt file or a text field.")

    if "application/json" in content_type:
        data: dict[str, Any] = await request.json()
        text = str(data.get("text") or data.get("raw_text") or "")
        title = str(data.get("title") or "paste.txt")
        if not text.strip():
            raise HTTPException(status_code=400, detail="JSON body must include non-empty 'text'.")
        return text, title

    body = (await request.body()).decode("utf-8")
    if body.strip():
        return body, "raw.txt"
    raise HTTPException(status_code=400, detail="Send raw text, JSON {text}, or a file upload.")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "Loom"}


@app.post("/api/ingest", response_model=StoryState)
async def ingest(request: Request) -> StoryState:
    text, title = await _read_ingest_payload(request)
    result = orchestrator.run(
        OrchestratorRequest(capability="ingest", raw_text=text, source_title=title)
    )
    if result.graph is None:
        raise HTTPException(status_code=500, detail="Ingestion produced no lore graph.")
    store.set(raw_text=text, graph=result.graph, title=title)
    return _story_state(text, result.graph)


@app.get("/api/sample", response_model=StoryState)
def sample() -> StoryState:
    text = SAMPLE_STORY_PATH.read_text(encoding="utf-8")
    result = orchestrator.run(
        OrchestratorRequest(
            capability="ingest",
            raw_text=text,
            source_title=SAMPLE_STORY_PATH.name,
        )
    )
    if result.graph is None:
        raise HTTPException(status_code=500, detail="Sample ingestion failed.")
    store.set(raw_text=text, graph=result.graph, title=SAMPLE_STORY_PATH.name)
    return _story_state(text, result.graph)


@app.post("/api/interview")
def interview(body: InterviewBody) -> dict[str, Any]:
    _, graph = _require_graph()
    try:
        build_context(graph, body.character_id, body.checkpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    question = _effective_question(body.message, body.history)
    result = orchestrator.run(
        OrchestratorRequest(
            capability="interview",
            graph=graph,
            character_id=body.character_id,
            checkpoint_id=body.checkpoint_id,
            question=question,
        )
    )
    turn = result.interview
    return {
        "character_id": body.character_id,
        "checkpoint_id": body.checkpoint_id,
        "message": body.message,
        "response": result.text,
        "refused_future": bool(turn.refused_future) if turn else False,
        "used_facts": turn.used_facts if turn else [],
        "passed": result.passed,
        "retries": result.retries,
        "critique": result.critique,
        "trace": result.trace,
    }


@app.post("/api/perspective")
def perspective(body: PerspectiveBody) -> dict[str, Any]:
    _, graph = _require_graph()
    try:
        build_context(graph, body.character_id, body.checkpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = orchestrator.run(
        OrchestratorRequest(
            capability="perspective",
            graph=graph,
            character_id=body.character_id,
            checkpoint_id=body.checkpoint_id,
        )
    )
    draft = result.perspective
    return {
        "character_id": body.character_id,
        "checkpoint_id": body.checkpoint_id,
        "prose": result.text,
        "interior": draft.interior if draft else None,
        "sensory_focus": draft.sensory_focus if draft else [],
        "passed": result.passed,
        "retries": result.retries,
        "critique": result.critique,
        "trace": result.trace,
    }


@app.post("/api/projects/{project_id}/spinoff", response_model=SpinoffResponse)
def spinoff(project_id: str, body: SpinoffBody) -> SpinoffResponse:
    _, graph = _require_graph()
    try:
        from narrative_context import resolve_character as _rc
        _rc(graph, body.character_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = orchestrator.run(
            OrchestratorRequest(
                capability="spinoff",
                graph=graph,
                character_id=body.character_id,
                spinoff_type=body.spinoff_type,
                tone=body.tone,
                length=body.length,
                focus_prompt=body.focus_prompt,
                language=body.language,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    draft = result.spinoff
    return SpinoffResponse(
        title=draft.title if draft else "Untitled Spin-off",
        story=result.text,
        canon_anchors=[
            CanonAnchorOut(
                event_id=a.event_id,
                event_title=a.event_title,
                how_used=a.how_used,
            )
            for a in (draft.canon_anchors if draft else [])
        ],
        invented_elements=draft.invented_elements if draft else [],
        audit=result.critique,
        trace=result.trace,
    )
