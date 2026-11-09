import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { confirmReset, refusalText } from "@/lib/matrix/confirm-reset";
import { useEffect, useState } from "react";
import { Shell, Panel, Empty } from "@/components/shell";
import { Button, Select, Input } from "@/components/ui";
import { useHydrated, useMccReaderError } from "@/lib/matrix/use-hydrated";
import { apiGetMcc } from "@/lib/matrix/api";
import { useSelectableWorlds } from "@/lib/matrix/use-selectable";
import { useMatrix } from "@/lib/matrix/store";
import { downloadJson } from "@/lib/matrix/normalize";

export const Route = createFileRoute("/chat/")({ component: ChatGate });

function ChatGate() {
  const nav = useNavigate();
  const hydrated = useHydrated();
  const readerError = useMccReaderError();   // Stand 06a (M3): the existing start reader's failure
  const activeUserId = useMatrix((s) => s.activeUserId);
  const sessions = useMatrix((s) => s.sessions);
  const worlds = useSelectableWorlds();
  const allWorlds = useMatrix((s) => s.worlds);
  const characters = useMatrix((s) => s.characters);
  const renameSession = useMatrix((s) => s.renameSession);
  const deleteSession = useMatrix((s) => s.deleteSession);
  const resetSessionChat = useMatrix((s) => s.resetSessionChat);
  const resetSessionRuntime = useMatrix((s) => s.resetSessionRuntime);
  const resetSessionMemory = useMatrix((s) => s.resetSessionMemory);
  const resetSessionUploads = useMatrix((s) => s.resetSessionUploads);
  const resetSessionFull = useMatrix((s) => s.resetSessionFull);
  const duplicateSession = useMatrix((s) => s.duplicateSession);
  const addSnapshot = useMatrix((s) => s.addSnapshot);
  const restoreSnapshot = useMatrix((s) => s.restoreSnapshot);
  const snapshots = useMatrix((s) => s.snapshots);
  const importSession = useMatrix((s) => s.importSession);
  // V61 (AMASTER §54 "jede Backendfunktion mit Produktwirkung ... sichtbar oder
  // prüfbar", §19 Resetarten): the reset buttons show what they did. Reads the
  // existing log owner (RESET_* / PERSIST_FAILED); no second state, no new route.
  const logs = useMatrix((s) => s.logs);
  const lastResetAny = logs.find((l) => l.code.startsWith("RESET_") || (l.code === "PERSIST_FAILED" && /reset/i.test(l.message)));
  const mine = sessions.filter((s) => s.userId === activeUserId);
  const [renameId, setRenameId] = useState("");
  const [renameVal, setRenameVal] = useState("");
  const [importErr, setImportErr] = useState<string | null>(null);
  // Stand 06a (M3, AMASTER §65 "Fehler duerfen nicht verschluckt werden"): an empty list is shown as "Keine Session"
  // only when the existing MCC reader CONFIRMS it; a failed read (e.g. 503 of the consent core) is a visible error.
  const [leer, setLeer] = useState<{ status: "offen" | "leer" | "fehler"; fehler?: string }>({ status: "offen" });
  useEffect(() => {
    if (!hydrated || !activeUserId || mine.length > 0) return;
    let aktiv = true;
    setLeer({ status: "offen" });
    apiGetMcc(activeUserId)
      .then((m) => {
        if (!aktiv) return;
        const eigene = ((m.sessions as { userId?: string }[] | undefined) ?? []).filter((x) => x.userId === activeUserId);
        setLeer(eigene.length === 0 ? { status: "leer" }
          : { status: "fehler", fehler: `${eigene.length} Session(s) auf dem Server, aber hier nicht geladen - Seite neu laden.` });
      })
      .catch((err) => {
        if (aktiv) setLeer({ status: "fehler", fehler: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      aktiv = false;
    };
  }, [hydrated, activeUserId, mine.length]);
  const ladeFehler = readerError || (leer.status === "fehler" ? leer.fehler || "unbekannt" : null);

  if (!hydrated) {
    return (
      <Shell title="Chat">
        {readerError ? (
          <p className="text-sm text-danger" role="alert" data-testid="sessions-load-error">
            Sessions konnten nicht geladen werden – technischer Fehler, keine leere Liste: {readerError}
          </p>
        ) : (
          <p className="text-sm text-muted">Lädt…</p>
        )}
      </Shell>
    );
  }

  return (
    <Shell title="Chat">
      <h1 className="font-display text-2xl font-semibold">MCC Chat</h1>
      <p className="mt-1 text-sm text-muted">Session wählen. Ohne Session kein Turn. Umbenennen, Reset und Snapshot schreiben denselben SQLite-Owner.</p>
      <Panel className="mt-5" title="Sessions dieses Users">
        {lastResetAny && lastResetAny.code === "PERSIST_FAILED" ? (
          <p className="mb-2 text-[11px] text-danger" data-testid="reset-error">
            {(() => {
              const r = refusalText(lastResetAny.message);   // V68 (Audit8): the refusal in plain German first
              const head = r.title === "Speichern fehlgeschlagen" ? "fehlgeschlagen" : r.title.toLowerCase();
              return `${new Date(lastResetAny.at).toLocaleTimeString()} · Reset ${head}${r.text ? `: ${r.text}` : ""} — ${lastResetAny.message}`;
            })()}
          </p>
        ) : null}
        {ladeFehler ? (
          <p className="mb-2 text-sm text-danger" role="alert" data-testid="sessions-load-error">
            Sessions konnten nicht geladen werden – technischer Fehler, keine leere Liste: {ladeFehler}
          </p>
        ) : mine.length === 0 ? (
          leer.status === "leer" || !activeUserId ? (
            <Empty>Keine Session. Unten anlegen — Welt muss ausdrücklich gewählt werden.</Empty>
          ) : (
            <p className="text-sm text-muted">Sessions werden geprüft…</p>
          )
        ) : null}
        <ul className="space-y-2">
          {mine.map((s) => (
            <li key={s.id} className="rounded-[12px] border border-border bg-bg px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm">{s.name}</p>
                  <p className="text-[11px] text-muted">
                    {worlds.find((w) => w.id === s.worldId)?.name} · Turn {s.turnIndex} · {s.scene.placeName}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => nav({ href: `/chat/${s.id}` })}>Öffnen</Button>
                  <Button
                    variant="line"
                    className="min-h-9 text-xs"
                    onClick={() => {
                      setRenameId(s.id);
                      setRenameVal(s.name);
                    }}
                  >
                    Umbenennen
                  </Button>
                  <Button variant="line" className="min-h-9 text-xs" onClick={() => confirmReset("chat", s.name) && resetSessionChat(s.id)}>
                    Chat-Reset
                  </Button>
                  <Button variant="line" className="min-h-9 text-xs" onClick={() => confirmReset("runtime", s.name) && resetSessionRuntime(s.id)}>
                    Runtime
                  </Button>
                  <Button variant="line" className="min-h-9 text-xs" onClick={() => confirmReset("memory", s.name) && resetSessionMemory(s.id)}>
                    Memory
                  </Button>
                  <Button variant="line" className="min-h-9 text-xs" onClick={() => confirmReset("uploads", s.name) && resetSessionUploads(s.id)}>
                    Uploads
                  </Button>
                  <Button variant="line" className="min-h-9 text-xs" onClick={() => confirmReset("full", s.name) && resetSessionFull(s.id)}>
                    Voll-Reset
                  </Button>
                  <Button variant="line" className="min-h-9 text-xs" onClick={() => addSnapshot(s.id, `Stand ${s.name}`)}>
                    Snapshot
                  </Button>
                  <Button
                    variant="line"
                    className="min-h-9 text-xs"
                    onClick={() => {
                      void duplicateSession(s.id).then((id) => {
                        if (id) nav({ href: `/chat/${id}` });
                      });
                    }}
                  >
                    Duplizieren
                  </Button>
                  <Button
                    variant="line"
                    className="min-h-9 text-xs"
                    onClick={() =>
                      downloadJson(`${s.name.replace(/\s+/g, "_")}.session.json`, {
                        kind: "matrix10-session-pack",
                        session: s,
                      })
                    }
                  >
                    Export
                  </Button>
                  <Button variant="danger" className="min-h-9 text-xs" onClick={() => confirmReset("delete", s.name) && deleteSession(s.id)}>
                    Löschen
                  </Button>
                </div>
              </div>
              {(() => {
                const last = logs.find((l) => l.sessionId === s.id && l.code.startsWith("RESET_"));
                if (!last) return null;
                const rt = Object.keys(s.runtimes || {}).length;
                const rel = (s.relations || []).length;
                const mem = (s.memories || []).length;
                const empty = rt === 0 && !s.avatarId && (s.scene?.presentIds || []).length === 0;
                return (
                  <p className="mt-1 text-[11px] text-muted" data-testid="reset-status">
                    {new Date(last.at).toLocaleTimeString()} · {last.message} — Stand jetzt: {rt} Runtime-Figuren, {rel} Beziehungen, {mem} Erinnerungen, Turn {s.turnIndex}
                    {empty ? " · keine Figur anwesend und kein Avatar: Runtime und Beziehungen haben nichts zurückzusetzen" : ""}
                  </p>
                );
              })()}
              {snapshots.filter((x) => x.sessionId === s.id).length ? (
                <ul className="mt-2 space-y-1 text-[11px] text-muted">
                  {snapshots
                    .filter((x) => x.sessionId === s.id)
                    .slice(0, 4)
                    .map((snap) => (
                      <li key={snap.id} className="flex items-center gap-2">
                        <span className="flex-1 truncate">{snap.name}</span>
                        <Button variant="ghost" className="min-h-8 px-2 text-xs" onClick={() => restoreSnapshot(snap.id)}>
                          Restore
                        </Button>
                      </li>
                    ))}
                </ul>
              ) : null}
              {renameId === s.id ? (
                <div className="mt-2 flex gap-2">
                  <Input value={renameVal} onChange={(e) => setRenameVal(e.target.value)} />
                  <Button
                    className="min-h-9 text-xs"
                    onClick={() => {
                      if (renameVal.trim()) renameSession(s.id, renameVal.trim());
                      setRenameId("");
                    }}
                  >
                    Speichern
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
        <NewSession worlds={worlds} allWorlds={allWorlds} characters={characters} />
        <label className="mt-3 inline-flex min-h-11 cursor-pointer items-center rounded-[12px] border border-border bg-elevated px-4 text-sm">
          Session-Packung importieren
          <input
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              setImportErr(null);
              void f.text().then((raw) => {
                try {
                  const pack = JSON.parse(raw) as { kind?: string; session?: (typeof sessions)[number] };
                  if (pack.kind !== "matrix10-session-pack" || !pack.session) {
                    setImportErr("Kein matrix10-session-pack.");
                    return;
                  }
                  // V66 (Audit5 E03): God/Regie rows of the file are taken over only on the owner's explicit yes
                  const ask = (m: string) =>
                    window.confirm(
                      `Die Datei enthält God-/Regie-Einträge, die dieser Server nicht selbst erfasst hat.\n\n${m}\n\nAls eigene Autorität übernehmen? (Nein = nichts wird importiert)`,
                    );
                  void importSession(pack.session, ask).then((id) => {
                    if (id) nav({ href: `/chat/${id}` });
                    else {
                      // V65Z (SPS-Audit V65Y A08): the import is one server transaction - refused means nothing was stored;
                      // the reason is the server's (write boundary or world), not a guess.
                      const why = useMatrix.getState().logs.find((l: { code: string; message: string }) => l.code === "PERSIST_FAILED" || l.code === "SESSION_IMPORT_WORLD");
                      setImportErr(`Import abgelehnt, nichts gespeichert${why ? ` — ${why.message}` : ""}`);
                    }
                  });
                } catch (err) {
                  setImportErr(err instanceof Error ? err.message : "Import fehlgeschlagen");
                }
              });
            }}
          />
        </label>
        {importErr ? <p className="mt-2 text-sm text-danger">{importErr}</p> : null}
      </Panel>
    </Shell>
  );
}

function NewSession({
  worlds,
  allWorlds,
  characters,
}: {
  worlds: { id: string; name: string; explicitOnly?: boolean }[];
  allWorlds: { id: string; startSituations: { id: string; title: string; presentNames?: string[] }[] }[];
  characters: { id: string; name: string; worldId: string; canBeAvatar?: boolean; isWorldNative?: boolean }[];
}) {
  const nav = useNavigate();
  const startSession = useMatrix((s) => s.startSession);
  const activeUserId = useMatrix((s) => s.activeUserId);
  const first = worlds.find((w) => !w.explicitOnly)?.id ?? worlds[0]?.id ?? "";
  const [worldId, setWorldId] = useState(first);
  const [avatarName, setAvatarName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sitId, setSitId] = useState("");
  const worldChars = characters.filter((c) => c.worldId === worldId);
  const avatars = worldChars.filter((c) => c.isWorldNative === false || Boolean(c.canBeAvatar));
  const stamm = worldChars.filter((c) => c.isWorldNative && !c.canBeAvatar);
  const situations = allWorlds.find((w) => w.id === worldId)?.startSituations || [];
  const startSit = situations.find((s) => s.id === sitId) ?? situations[0];
  const startNames = new Set((startSit?.presentNames ?? worldChars.filter((c) => c.isWorldNative).map((c) => c.name)).map((n) => n.toLowerCase()));
  return (
    <form
      className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap"
      onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        const id = String(fd.get("world") || worldId || "");
        const picked = String(fd.get("avatar") || "");
        const sit = String(fd.get("situation") || "");
        // V65F (AMASTER §19 "aktive Figuren festlegen"): who is present at the start is chosen here.
        // Unchanged boxes keep the chosen start situation in charge (also a second situation).
        const chosenIds = fd.getAll("present").map(String);
        const shownIds = worldChars.filter((c) => c.isWorldNative && startNames.has(c.name.toLowerCase())).map((c) => c.id);
        const presentIds = [...chosenIds].sort().join("|") === [...shownIds].sort().join("|") ? undefined : chosenIds;
        const named = avatarName.trim();
        if (!activeUserId) {
          setErr("Kein aktiver User — zuerst User wählen.");
          return;
        }
        if (!id) {
          setErr("Bitte eine Welt wählen.");
          return;
        }
        setBusy(true);
        setErr(null);
        void startSession({
          worldId: id,
          userId: activeUserId,
          avatarId: picked || undefined,
          avatarName: named || undefined,
          situationId: sit || undefined,
          presentIds,
        }).then((sid) => {
          setBusy(false);
          if (!sid) {
            const fail = useMatrix.getState().logs.find((l) => l.code === "PERSIST_FAILED");
            setErr(fail?.message || "Session konnte nicht angelegt werden.");
            return;
          }
          nav({ href: `/chat/${sid}` });
        });
      }}
    >
      <Select name="world" value={worldId} onChange={(e) => { setWorldId(e.target.value); setSitId(""); }} required>
        <option value="" disabled>
          Welt ausdrücklich wählen
        </option>
        {worlds.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </Select>
      <label className="text-xs text-muted">
        Avatar wählen oder unten neu anlegen
        <Select name="avatar" defaultValue="" className="mt-1">
          <option value="">kein Avatar / neu anlegen</option>
          {avatars.map((c) => (
            <option key={c.id} value={c.id}>
              Avatar: {c.name}
            </option>
          ))}
          {stamm.map((c) => (
            <option key={c.id} value={c.id}>
              Stamm als Avatar: {c.name}
            </option>
          ))}
        </Select>
      </label>
      <Input
        name="avatarName"
        value={avatarName}
        onChange={(e) => setAvatarName(e.target.value)}
        placeholder="Neuen Avatar anlegen — Name"
      />
      <Select name="situation" value={sitId} onChange={(e) => setSitId(e.target.value)}>
        <option value="">Startsituation Standard</option>
        {situations.map((s) => (
          <option key={s.id} value={s.id}>
            {s.title}
          </option>
        ))}
      </Select>
      <fieldset key={`${worldId}:${sitId}`} className="w-full text-xs text-muted">
        <legend>Anwesend zu Beginn (Vorgabe aus der Startsituation, abwählbar)</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {worldChars
            .filter((c) => c.isWorldNative)
            .map((c) => (
              <label key={c.id} className="inline-flex min-h-11 items-center gap-2 text-sm text-fg">
                <input type="checkbox" name="present" value={c.id} defaultChecked={startNames.has(c.name.toLowerCase())} />
                {c.name}
              </label>
            ))}
        </div>
      </fieldset>
      <Button type="submit" disabled={busy}>
        {busy ? "Speichert…" : "Neue Session"}
      </Button>
      {err ? <p className="w-full text-sm text-danger">{err}</p> : null}
    </form>
  );
}
