import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

const API_URL = "https://loom-narrative-engine.onrender.com";

type Character = {
  id: string;
  name: string;
  aliases: string[];
  role: string | null;
  traits: string[];
};

type Checkpoint = {
  id: string;
  order: number;
  time_marker: string | null;
  event: string;
  characters_involved: string[];
};

type Knowledge = {
  id: string;
  valid_from: string;
  valid_until: string | null;
  summary: string;
  known_facts: string[];
  superseded_beliefs: string[];
};

type StoryState = {
  source_title: string;
  story: string;
  characters: Character[];
  checkpoints: Checkpoint[];
  knowledge: Knowledge[];
};

type ChatItem = {
  role: "user" | "character";
  content: string;
  refused?: boolean;
};

type Tab = "interview" | "perspective";

function orderOf(checkpoints: Checkpoint[], id: string | null): number {
  if (!id) return -1;
  return checkpoints.find((item) => item.id === id)?.order ?? -1;
}

function knownHorizon(state: StoryState, checkpointId: string) {
  const target = orderOf(state.checkpoints, checkpointId);
  const remembered = state.knowledge.filter(
    (item) => orderOf(state.checkpoints, item.valid_from) <= target,
  );
  const active = remembered.filter((item) => {
    const until = item.valid_until ? orderOf(state.checkpoints, item.valid_until) : null;
    return until === null || until > target;
  });
  const sealed = state.knowledge.filter(
    (item) => orderOf(state.checkpoints, item.valid_from) > target,
  );
  const facts = remembered.flatMap((item) => item.known_facts);
  return { remembered, active, sealed, facts: [...new Set(facts)] };
}

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    return JSON.stringify(data.detail ?? data);
  } catch {
    return response.statusText;
  }
}

export default function App() {
  const fileRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<StoryState | null>(null);
  const [characterId, setCharacterId] = useState("");
  const [checkpointId, setCheckpointId] = useState("");
  const [tab, setTab] = useState<Tab>("interview");
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [scene, setScene] = useState<{
    prose: string;
    interior: string | null;
    sensory_focus: string[];
  } | null>(null);

  const character = state?.characters.find((item) => item.id === characterId);
  const checkpoints = state?.checkpoints ?? [];
  const checkpointIndex = Math.max(
    0,
    checkpoints.findIndex((item) => item.id === checkpointId),
  );
  const checkpoint = checkpoints[checkpointIndex];
  const horizon = useMemo(() => {
    if (!state || !checkpointId) return null;
    return knownHorizon(state, checkpointId);
  }, [state, checkpointId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat, busy]);

  function applyStory(next: StoryState) {
    setState(next);
    const mara = next.characters.find((item) => item.id === "mara-vale") ?? next.characters[0];
    const mid =
      next.checkpoints.find((item) => item.id === "cp_05") ??
      next.checkpoints[Math.floor(next.checkpoints.length / 2)] ??
      next.checkpoints[0];
    setCharacterId(mara?.id ?? "");
    setCheckpointId(mid?.id ?? "");
    setChat([]);
    setScene(null);
    setError(null);
  }

  async function loadSample() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("https://loom-narrative-engine.onrender.com/api/sample");
      if (!response.ok) throw new Error(await readError(response));
      applyStory(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sample");
    } finally {
      setBusy(false);
    }
  }

  async function ingestFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch("/api/ingest", { method: "POST", body });
      if (!response.ok) throw new Error(await readError(response));
      applyStory(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendInterview(event?: FormEvent) {
    event?.preventDefault();
    if (!draft.trim() || !state) return;
    const message = draft.trim();
    setDraft("");
    setChat((prev) => [...prev, { role: "user", content: message }]);
    setBusy(true);
    setError(null);
    try {
      const history = [...chat, { role: "user" as const, content: message }].map((item) => ({
        role: item.role,
        content: item.content,
      }));
      const response = await fetch("/api/interview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          character_id: characterId,
          checkpoint_id: checkpointId,
          message,
          history,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setChat((prev) => [
        ...prev,
        { role: "character", content: data.response, refused: data.refused_future },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Interview failed");
    } finally {
      setBusy(false);
    }
  }

  async function runPerspective() {
    if (!state) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/perspective", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          character_id: characterId,
          checkpoint_id: checkpointId,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setScene({
        prose: data.prose,
        interior: data.interior,
        sensory_focus: data.sensory_focus ?? [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Perspective failed");
    } finally {
      setBusy(false);
    }
  }

  function selectCheckpoint(index: number) {
    const next = checkpoints[index];
    if (!next) return;
    setCheckpointId(next.id);
    setChat([]);
    setScene(null);
  }

  return (
    <div className="min-h-screen bg-ink text-mist">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(196,165,116,0.08),_transparent_55%)]" />
      <div className="relative mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-6 md:px-8">
        <header className="mb-6 flex flex-col gap-4 rounded-3xl border border-line bg-panel/90 p-5 shadow-[0_20px_80px_rgba(0,0,0,0.35)] md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs tracking-[0.35em] text-brass uppercase">Multi-agent narrative engine</p>
            <h1 className="font-display text-4xl text-brass md:text-5xl">Loom</h1>
            <p className="mt-1 max-w-xl text-sm text-mute">
              Interview characters inside a sealed knowledge horizon. They cannot know what has not yet happened.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileRef}
              type="file"
              accept=".txt,text/plain"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void ingestFile(file);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="rounded-full border border-line px-4 py-2 text-sm hover:border-brass hover:text-brass"
            >
              Upload story (.txt)
            </button>
            <button
              type="button"
              onClick={() => void loadSample()}
              className="rounded-full bg-brass px-4 py-2 text-sm font-medium text-ink hover:bg-[#d4b98a]"
            >
              Load sample story
            </button>
          </div>
        </header>

        {error ? (
          <div className="mb-4 rounded-2xl border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        {!state ? (
          <EmptyState busy={busy} onSample={() => void loadSample()} onUpload={() => fileRef.current?.click()} />
        ) : (
          <div className="grid flex-1 gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
            <aside className="space-y-4">
              <section className="rounded-3xl border border-line bg-panel p-4">
                <label className="text-xs tracking-[0.2em] text-mute uppercase">Character</label>
                <select
                  value={characterId}
                  onChange={(event) => {
                    setCharacterId(event.target.value);
                    setChat([]);
                    setScene(null);
                  }}
                  className="mt-2 w-full rounded-2xl border border-line bg-panel-2 px-3 py-2 text-mist outline-none focus:border-brass"
                >
                  {state.characters.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                      {item.role ? ` — ${item.role}` : ""}
                    </option>
                  ))}
                </select>
                {character?.traits.length ? (
                  <p className="mt-3 text-xs text-mute">{character.traits.join(" · ")}</p>
                ) : null}
              </section>

              <section className="rounded-3xl border border-line bg-panel p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <label className="text-xs tracking-[0.2em] text-mute uppercase">Timeline checkpoint</label>
                  <span className="font-mono text-xs text-brass">{checkpoint?.id}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, checkpoints.length - 1)}
                  value={checkpointIndex}
                  onChange={(event) => selectCheckpoint(Number(event.target.value))}
                  className="mt-4 w-full accent-[#c4a574]"
                />
                <div className="mt-2 flex justify-between">
                  <button
                    type="button"
                    className="text-xs text-brass hover:underline"
                    onClick={() => selectCheckpoint(Math.max(0, checkpointIndex - 1))}
                  >
                    ← Earlier
                  </button>
                  <button
                    type="button"
                    className="text-xs text-brass hover:underline"
                    onClick={() => selectCheckpoint(Math.min(checkpoints.length - 1, checkpointIndex + 1))}
                  >
                    Later →
                  </button>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-mist/90">{checkpoint?.event}</p>
                {checkpoint?.time_marker ? (
                  <p className="mt-2 text-xs text-sea">{checkpoint.time_marker.replaceAll("_", " ")}</p>
                ) : null}
              </section>

              <section className="rounded-3xl border border-line bg-panel">
                <button
                  type="button"
                  className="flex w-full items-center justify-between px-4 py-3 text-left"
                  onClick={() => setDrawerOpen((open) => !open)}
                >
                  <span className="text-xs tracking-[0.18em] text-mute uppercase">
                    Inspect active knowledge horizon
                  </span>
                  <span className="text-brass">{drawerOpen ? "–" : "+"}</span>
                </button>
                {drawerOpen && horizon ? (
                  <div className="space-y-3 border-t border-line px-4 py-3">
                    <p className="text-xs text-mute">
                      {character?.name} at {checkpoint?.id} knows {horizon.facts.length} facts.
                      {horizon.sealed.length ? ` ${horizon.sealed.length} later windows are sealed.` : ""}
                    </p>
                    <div>
                      <p className="mb-1 text-[11px] tracking-widest text-brass uppercase">Currently valid</p>
                      <ul className="space-y-2">
                        {horizon.active.map((item) => (
                          <li key={item.id} className="rounded-xl bg-panel-2 p-2 text-xs leading-relaxed">
                            {item.summary}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="mb-1 text-[11px] tracking-widest text-brass uppercase">Remembered facts</p>
                      <ul className="max-h-48 space-y-1 overflow-y-auto text-xs text-mute">
                        {horizon.facts.map((fact) => (
                          <li key={fact}>· {fact}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ) : null}
              </section>
            </aside>

            <main className="flex min-h-[640px] flex-col rounded-3xl border border-line bg-panel">
              <div className="flex gap-2 border-b border-line p-3">
                {(
                  [
                    ["interview", "Interactive interview"],
                    ["perspective", "Perspective shift"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setTab(id)}
                    className={`rounded-full px-4 py-2 text-sm ${
                      tab === id ? "bg-brass text-ink" : "text-mute hover:text-mist"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {tab === "interview" ? (
                <div className="flex min-h-0 flex-1 flex-col">
                  <div className="flex-1 space-y-3 overflow-y-auto p-5">
                    {chat.length === 0 ? (
                      <p className="text-sm text-mute">
                        Ask {character?.name ?? "the character"} anything. At this checkpoint they cannot
                        acknowledge later events.
                      </p>
                    ) : null}
                    {chat.map((item, index) => (
                      <div
                        key={`${item.role}-${index}`}
                        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                          item.role === "user"
                            ? "ml-auto bg-brass/15 text-mist"
                            : "bg-panel-2 text-mist"
                        }`}
                      >
                        <p className="mb-1 text-[10px] tracking-widest text-brass uppercase">
                          {item.role === "user" ? "You" : character?.name}
                          {item.refused ? " · refuses future knowledge" : ""}
                        </p>
                        {item.content}
                      </div>
                    ))}
                    {busy ? <p className="text-xs text-mute">Weaving a reply…</p> : null}
                    <div ref={chatEndRef} />
                  </div>
                  <form onSubmit={sendInterview} className="border-t border-line p-4">
                    <div className="flex gap-2">
                      <textarea
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && !event.shiftKey) {
                            event.preventDefault();
                            void sendInterview();
                          }
                        }}
                        rows={2}
                        placeholder={`Speak to ${character?.name ?? "the character"}…`}
                        className="flex-1 resize-none rounded-2xl border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-brass"
                      />
                      <button
                        type="submit"
                        disabled={busy || !draft.trim()}
                        className="self-end rounded-2xl bg-brass px-4 py-2 text-sm font-medium text-ink disabled:opacity-40"
                      >
                        Send
                      </button>
                    </div>
                  </form>
                </div>
              ) : (
                <div className="flex flex-1 flex-col p-5">
                  <p className="mb-4 text-sm text-mute">
                    Rewrite {checkpoint?.id} strictly through {character?.name}&apos;s senses and private thoughts.
                  </p>
                  <button
                    type="button"
                    onClick={() => void runPerspective()}
                    disabled={busy}
                    className="mb-5 w-fit rounded-full bg-brass px-4 py-2 text-sm font-medium text-ink disabled:opacity-40"
                  >
                    Shift perspective
                  </button>
                  {scene ? (
                    <article className="space-y-4">
                      <p className="font-display text-xl leading-relaxed text-mist">{scene.prose}</p>
                      {scene.interior ? (
                        <p className="border-l-2 border-brass/50 pl-4 text-sm text-mute italic">{scene.interior}</p>
                      ) : null}
                      {scene.sensory_focus.length ? (
                        <div className="flex flex-wrap gap-2">
                          {scene.sensory_focus.map((item) => (
                            <span key={item} className="rounded-full border border-line px-3 py-1 text-xs text-sea">
                              {item}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ) : (
                    <p className="text-sm text-mute">No scene generated yet.</p>
                  )}
                </div>
              )}
            </main>
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState({
  busy,
  onSample,
  onUpload,
}: {
  busy: boolean;
  onSample: () => void;
  onUpload: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-3xl border border-dashed border-line bg-panel/60 px-6 py-20 text-center">
      <div className="thread mb-6 h-px w-48" />
      <h2 className="font-display text-3xl text-brass">Thread a story into the engine</h2>
      <p className="mt-3 max-w-lg text-sm text-mute">
        Load the drowned-coast sample, or upload a .txt file. Loom will extract characters, checkpoints, and
        time-bounded knowledge, then let you interview anyone from inside a single hour.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={onSample}
          disabled={busy}
          className="rounded-full bg-brass px-5 py-2 text-sm font-medium text-ink disabled:opacity-40"
        >
          {busy ? "Loading…" : "Load sample story"}
        </button>
        <button
          type="button"
          onClick={onUpload}
          className="rounded-full border border-line px-5 py-2 text-sm hover:border-brass"
        >
          Upload .txt
        </button>
      </div>
    </div>
  );
}
