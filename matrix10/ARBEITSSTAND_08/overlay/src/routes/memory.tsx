import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Shell, Panel, Empty } from "@/components/shell";
import { Select, Button, Input } from "@/components/ui";
import { useMatrix } from "@/lib/matrix/store";
import { useHydrated } from "@/lib/matrix/use-hydrated";
import { apiGetSession, apiListDocumentIndex, apiListReviews, apiRecall, apiSearchDocumentIndex, apiVectorSearch } from "@/lib/matrix/api";
import { hydrateSession } from "@/lib/matrix/normalize";
import type { MemoryKind, Session } from "@/lib/matrix/types";

export const Route = createFileRoute("/memory")({ component: MemoryPage });

const VIEWS = ["session", "stamm", "world", "cache", "index", "review"] as const;
const KINDS: MemoryKind[] = [
  "erlebt",
  "gesehen",
  "gehoert",
  "betroffen",
  "gesagt",
  "getan",
  "erzaehlt",
  "gelesen",
  "informiert",
  "vermutet",
  "verdraengt",
  "erschlossen",
  "geglaubt",
  "behauptet",
  "bestritten",
  "unsicher",
  "vergessen",
  "upload",
];

type LayerRow = { id: string; kicker: string; text: string };

function MemoryPage() {
  const hydrated = useHydrated();
  const sessions = useMatrix((s) => s.sessions);
  const characters = useMatrix((s) => s.characters);
  const worlds = useMatrix((s) => s.worlds);
  const reviews = useMatrix((s) => s.reviews);
  const addMemory = useMatrix((s) => s.addMemory);
  const patchCharacter = useMatrix((s) => s.patchCharacter);
  const patchWorld = useMatrix((s) => s.patchWorld);
  const acceptKernelSession = useMatrix((s) => s.acceptKernelSession);
  const [sessionId, setSessionId] = useState("");
  const [charId, setCharId] = useState("");
  const [layer, setLayer] = useState<(typeof VIEWS)[number]>("session");
  const [cue, setCue] = useState("");
  const [hits, setHits] = useState("");
  const [memText, setMemText] = useState("");
  const [memKind, setMemKind] = useState<MemoryKind>("erlebt");
  const [cacheRows, setCacheRows] = useState<LayerRow[]>([]);
  const [indexRows, setIndexRows] = useState<LayerRow[]>([]);
  const [reviewRows, setReviewRows] = useState<LayerRow[]>([]);
  const session = sessions.find((s) => s.id === sessionId) ?? sessions[0];
  const world = worlds.find((w) => w.id === session?.worldId);

  useEffect(() => {
    if (layer !== "cache" || !session?.id) {
      if (layer !== "cache") setCacheRows([]);
      return;
    }
    void apiRecall(session.id, cue)
      .then((r) => {
        const list = ((r.hits as { id?: string; text?: string; sourceMemoryId?: string }[]) || []).map((h, i) => ({
          id: h.id || `cache-${i}`,
          kicker: `cache · abgeleitet von Memory ${h.sourceMemoryId || h.id || ""}`,
          text: h.text || "",
        }));
        setCacheRows(list);
        setHits(list.length ? list.map((x) => x.text).join(" · ") : "keine Treffer");
      })
      .catch((e) => {
        setCacheRows([]);
        setHits(e instanceof Error ? e.message : "Recall fehlgeschlagen");
      });
  }, [layer, session?.id, cue]);

  useEffect(() => {
    if (layer !== "index") {
      setIndexRows([]);
      return;
    }
    const load = cue.trim()
      ? apiSearchDocumentIndex(cue)
      : apiListDocumentIndex();
    void load
      .then((payload) => {
        const entries = (payload.entries as { id?: string; sourceDocumentId?: string; title?: string; excerpt?: string }[]) || [];
        const searchHits = (payload.hits as { id?: string; sourceDocumentId?: string; title?: string; excerpt?: string }[]) || [];
        const src = searchHits.length ? searchHits : entries;
        const rows = src.map((h, i) => ({
          id: String(h.sourceDocumentId || h.id || `idx-${i}`),
          kicker: `index · abgeleitet von Dokument ${h.sourceDocumentId || h.id || ""}`,
          text: h.title || h.excerpt || String(h.sourceDocumentId || h.id || ""),
        }));
        setIndexRows(rows);
        setHits(rows.length ? rows.map((x) => x.text).join(" · ") : "keine Treffer");
      })
      .catch((e) => {
        setIndexRows([]);
        setHits(e instanceof Error ? e.message : "Index fehlgeschlagen");
      });
  }, [layer, cue]);

  useEffect(() => {
    if (layer !== "review") {
      setReviewRows([]);
      return;
    }
    const local = reviews
      .filter((r) => !session || r.sourceSessionId === session.id || r.worldId === session.worldId)
      .map((r) => ({
        id: r.id,
        kicker: `review · ${r.kind} · ${r.status}`,
        text: `${r.field}: ${r.newValue || r.reason}`,
      }));
    setReviewRows(local);
    void apiListReviews()
      .then((r) => {
        const remote = (
          (r.reviews as {
            id?: string;
            kind?: string;
            status?: string;
            field?: string;
            newValue?: string;
            reason?: string;
            sourceSessionId?: string;
            worldId?: string;
          }[]) || []
        )
          .filter((item) => !session || item.sourceSessionId === session.id || item.worldId === session.worldId)
          .map((item, i) => ({
            id: item.id || `rev-${i}`,
            kicker: `review · ${item.kind || "item"} · ${item.status || "open"}`,
            text: `${item.field || ""}: ${item.newValue || item.reason || ""}`,
          }));
        const seen = new Set(local.map((x) => x.id));
        setReviewRows([...local, ...remote.filter((x) => !seen.has(x.id))]);
      })
      .catch((e) => {
        setHits(e instanceof Error ? e.message : "Reviews nicht lesbar");
      });
  }, [layer, reviews, session?.id, session?.worldId]);

  const layerRows: LayerRow[] = useMemo(() => {
    if (layer === "cache") return cacheRows;
    if (layer === "index") return indexRows;
    if (layer === "review") return reviewRows;
    if (layer === "stamm") {
      const chars = charId ? characters.filter((c) => c.id === charId) : characters.filter((c) => c.worldId === session?.worldId);
      return chars.flatMap((c) =>
        (c.knowledge || []).map((k, i) => ({
          id: `${c.id}-know-${i}`,
          kicker: `stamm · ${c.name} · characters.knowledge`,
          text: k,
        })),
      );
    }
    if (layer === "world") {
      const secrets = (world?.secrets || []).map((s, i) => ({ id: `secret-${i}`, kicker: "world · secret", text: s }));
      const history = (world?.history || []).map((s, i) => ({ id: `hist-${i}`, kicker: "world · history", text: s }));
      const limits = (world?.knowledgeLimits || []).map((s, i) => ({
        id: `limit-${i}`,
        kicker: "world · limit",
        text: s,
      }));
      return [...secrets, ...history, ...limits];
    }
    return (session?.memories ?? [])
      .filter((m) => !charId || m.characterId === charId)
      .map((m) => ({
        id: m.id,
        kicker: `${characters.find((c) => c.id === m.characterId)?.name || m.characterId} · ${m.kind} · Turn ${m.turn} · session`,
        text: m.text,
      }));
  }, [layer, cacheRows, indexRows, reviewRows, session, charId, characters, world]);

  if (!hydrated) {
    return (
      <Shell title="Gedächtnis">
        <p className="text-sm text-muted">Lädt…</p>
      </Shell>
    );
  }

  return (
    <Shell title="Gedächtnis">
      <h1 className="font-display text-2xl font-semibold">Gedächtnis</h1>
      <div className="mt-3 flex flex-wrap gap-2">
        <input className="min-h-9 rounded-md border border-border bg-elevated px-2 text-sm" value={cue} onChange={(e) => setCue(e.target.value)} placeholder="Recall-Stichwort" />
        <button
          type="button"
          className="rounded-md border border-border px-3 text-sm"
          data-k02="figur-recall"
          onClick={async () => {
            if (!session?.id) return;
            if (charId) {
              // Stand 08 / K-02: what THIS figure recalls (the reader of her turn), never the overlap of all figures
              try {
                const r = await apiRecall(session.id, cue, charId);
                const mems = (r.memories as { kind?: string; text?: string }[]) || [];
                const name = String(r.characterName || charId);
                setHits(mems.length
                  ? `Abruf von ${name} (kanonisch, ${mems.length} Erinnerungen, ${((r.facts as unknown[]) || []).length} bekannte Ereignisse): ` +
                    mems.map((m) => `${m.kind}: ${m.text}`).join(" · ")
                  : `Abruf von ${name} (kanonisch): keine Erinnerung zu diesem Stichwort.`);
              } catch (e) {
                setHits(`Recall fehlgeschlagen: ${e instanceof Error ? e.message : String(e)}`);
              }
              return;
            }
            const r = await apiRecall(session.id, cue);
            const list = ((r.hits as { text?: string }[]) || []).map((h) => h.text || "").join(" · ");
            setHits(list ? `Cache (abgeleitet, kein Kanon, alle Figuren): ${list} — für den Abruf einer Figur oben die Figur wählen.` : "keine Treffer");
            setLayer("cache");
          }}
        >
          Recall
        </button>
        <button
          type="button"
          className="rounded-md border border-border px-3 text-sm"
          onClick={async () => {
            const r = await apiSearchDocumentIndex(cue);
            const list = ((r.hits as { title?: string; sourceDocumentId?: string; id?: string }[]) || [])
              .map((h) => h.title || h.sourceDocumentId || h.id || "")
              .join(" · ");
            setHits(list || "keine Treffer");
            setLayer("index");
          }}
        >
          Suche
        </button>
        <button
          type="button"
          className="rounded-md border border-border px-3 text-sm"
          onClick={async () => {
            const r = await apiVectorSearch(cue);
            const list = ((r.hits as { title?: string; text?: string; id?: string; kind?: string }[]) || [])
              .map((h) => h.title || h.text || h.kind || h.id || "")
              .join(" · ");
            setHits(list || "keine Vektor-Treffer");
            setLayer("index");
          }}
        >
          Vektor
        </button>
      </div>
      {hits ? <p className="mt-2 text-sm text-muted">{hits}</p> : null}
      <p className="mt-1 text-sm text-muted">
        Stammwissen ist Charakterwissen. Sessionmemory ist die Session. Weltwissen ist die Welt. Cache ist abgeleiteter Recall, kein Kanon. Index ist der Dokumentindex, nicht das Dokument. Review sind Vorschläge. Vergessen löscht keine SceneFacts.
      </p>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <Select value={session?.id ?? ""} onChange={(e) => setSessionId(e.target.value)}>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
        <Select value={charId} onChange={(e) => setCharId(e.target.value)}>
          <option value="">alle Figuren</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select value={layer} onChange={(e) => setLayer(e.target.value as (typeof VIEWS)[number])}>
          {VIEWS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </Select>
      </div>
      {session && (layer === "session" || layer === "stamm" || layer === "world") ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {layer === "session" ? (
            <Select value={memKind} onChange={(e) => setMemKind(e.target.value as MemoryKind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </Select>
          ) : null}
          <Input
            value={memText}
            onChange={(e) => setMemText(e.target.value)}
            placeholder={
              layer === "stamm" ? "Stammwissen (Charakter)" : layer === "world" ? "Weltwissen" : "Sessionmemory"
            }
          />
          <Button
            className="min-h-9 text-xs"
            onClick={() => {
              const text = memText.trim();
              if (!text) return;
              if (layer === "stamm") {
                if (!charId) return;
                const char = characters.find((c) => c.id === charId);
                patchCharacter(charId, { knowledge: [...(char?.knowledge || []), text] });
                setMemText("");
                return;
              }
              if (layer === "world") {
                if (!world) return;
                patchWorld(world.id, { secrets: [...(world.secrets || []), text] });
                setMemText("");
                return;
              }
              if (!charId) return;
              addMemory(session.id, {
                characterId: charId,
                kind: memKind,
                text,
                salience: 0.6,
                turn: session.turnIndex,
                witnesses: [charId],
                layer: "session",
                truthStatus: "canon",
              });
              setMemText("");
            }}
          >
            Speichern
          </Button>
        </div>
      ) : null}
      <Panel className="mt-4">
        {layerRows.length === 0 ? <Empty>Keine Erinnerungen in dieser Schicht.</Empty> : null}
        <ul className="space-y-2">
          {layerRows.map((m) => (
            <li key={m.id} className="rounded-[12px] border border-border bg-bg px-3 py-2 text-sm">
              <p className="text-[11px] text-faint">{m.kicker}</p>
              <p className="mt-1">{m.text}</p>
            </li>
          ))}
        </ul>
      </Panel>
      {session ? (
        <Panel className="mt-4" title="WitnessKnowledge (Pointer, nicht Memory)">
          <p className="mb-2 text-xs text-muted">Wer hat welchen Fact gesehen/gehört/erlitten. Abwesende stehen hier nicht, ohne Informationsweg.</p>
          <Button
            variant="line"
            className="mb-3 min-h-9 text-xs"
            onClick={async () => {
              const got = await apiGetSession(session.id);
              const next = hydrateSession({ ...session, ...(got.session as unknown as Session) });
              acceptKernelSession(next);
              const wk = next.witnessKnowledge || [];
              setHits(
                wk.length
                  ? wk
                      .slice(0, 24)
                      .map((w) => {
                        const cid = w.characterId || w.character_id || "";
                        const nm = characters.find((c) => c.id === cid)?.name ?? cid;
                        return `${nm}:${w.access}@${w.fact_id}`;
                      })
                      .join(" · ")
                  : "keine Pointer",
              );
            }}
          >
            Witness vom Reader laden
          </Button>
          <ul className="space-y-1 text-xs text-muted">
            {(session.witnessKnowledge ?? [])
              .filter((w) => !charId || (w.characterId || w.character_id) === charId)
              .slice(-16)
              .reverse()
              .map((w, i) => {
                const cid = w.characterId || w.character_id || "";
                return (
                  <li key={`${cid}-${w.fact_id}-${i}`}>
                    {characters.find((c) => c.id === cid)?.name ?? cid} · {w.access} · Fact {w.fact_id} · Turn {w.turn}
                  </li>
                );
              })}
          </ul>
        </Panel>
      ) : null}
      {session ? (
        <Panel className="mt-4" title="Unsicherheit, Quellen, Propositionen, Beziehungen, Knowledge Paths">
          <p className="text-xs text-muted">
            Unsicher {session.memories.filter((m) => m.truthStatus && m.truthStatus !== "canon").length} · Quellen{" "}
            {session.memories.filter((m) => m.kind === "gelesen" || m.kind === "informiert").length} · Propositionen{" "}
            {session.propositions.length} · Beziehungen {session.relations.length} · Knowledge-Paths{" "}
            {(session.witnessKnowledge || []).length}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-muted">
            {session.propositions.slice(0, 6).map((p) => (
              <li key={p.id}>
                Prop {p.status}: {p.text}
              </li>
            ))}
            {session.relations.slice(0, 6).map((r) => (
              <li key={`${r.fromId}-${r.toId}`}>
                {r.fromId} → {r.toId} · {r.kind}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </Shell>
  );
}
