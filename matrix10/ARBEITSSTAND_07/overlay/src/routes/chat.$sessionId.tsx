import { canExplicitlyRetryPendingAttempt } from "../lib/matrix/pending-attempt-controls";
import { createFileRoute, Link } from "@tanstack/react-router";
import { confirmReset } from "@/lib/matrix/confirm-reset";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Chip, Input, Select, Switch, Textarea } from "@/components/ui";
import { Shell } from "@/components/shell";
import { extractTextFromFile } from "@/lib/matrix/epub";
import { textFromUpload } from "@/lib/matrix/ocr";
import {
  detectAddressed,
  pickSpeaker,
} from "@/lib/matrix/session-engine";
import { canPerform } from "@/lib/matrix/event-engine";
import { kernelAutochatGate, kernelCommitFigure, kernelFate, kernelGod, kernelMove, kernelPrepare, kernelPerception, kernelPresence, kernelPuppet, kernelRegie, type KernelTrace } from "@/lib/matrix/kernel-bridge";
import { responseReadbackStatus } from "@/lib/matrix/response-readback";
import { hydrateCharacter } from "@/lib/matrix/normalize";
import { actorHeader, apiGetMcc, apiGetSession, apiFormulate, apiSpeechStt, apiSpeechTts, readStoredActor } from "@/lib/matrix/api";
import { useMatrix, rebindStoredActor } from "@/lib/matrix/store";
import { useHydrated } from "@/lib/matrix/use-hydrated";
import { uid } from "@/lib/matrix/ids";
import { eingabeHinweis, identitaetsKlaerung, klaerungLabel, planIncompleteMeldung, type KlaerungAntwort, type KlaerungFrage } from "@/lib/matrix/eingabe-hinweis";
import type { FormulateResult, GodScope, Session, SpeakerMode, Spiegel, StammCharacter, SynapseFire, UploadMode } from "@/lib/matrix/types";
import { cn } from "@/lib/cn";
import { makeOutsiderAvatar } from "@/lib/matrix/seed-gasthaus";

// V65U (Plan U4/U5): the server's read view of the open input (kernel.pending_input_view).
type PendingInputView = {
  turnTruthId: string;
  text: string;
  speakerId?: string | null;
  targetId?: string | null;
  turn?: number | null;
  attempt?: { state?: string; error?: string } | null;
  attemptRunning: boolean;
  // P23: an attempt that is still running or not proven ended blocks both
  // repeat and close until the authoritative server read resolves it.
  attemptUnklar?: boolean;
};
const ATTEMPT_DE: Record<string, string> = {
  laeuft: "abgebrochen (Serverprozess beendet)",
  provider_fehler: "Provider-Fehler",
  formuliert: "formuliert, nicht gespeichert",
};

export const Route = createFileRoute("/chat/$sessionId")({ component: ChatPage });

// V92 Paket 14 (Entscheidung 4): the stored speaker binding of the session, only when it still binds something real
// (the avatar exists, the figure belongs to this world); otherwise "" = the user has to choose again, nothing is written.
function boundSpeakAs(s: Session | undefined, chars: StammCharacter[]): string {
  const v = String(s?.speakAs ?? "");
  if (v === "avatar") return s?.avatarId ? v : "";
  if (v.startsWith("char:")) return chars.some((c) => c.id === v.slice(5)) ? v : "";
  return ["operator", "observer", "regie", "gott"].includes(v) ? v : "";
}

/**
 * A Puppet follow-up may only react to the newly committed, validated speech/action
 * facts. Names in raw input, stale UI selection and rejected proposals are not facts.
 * This function selects no speaker; it only exposes the canonical recipient and cause.
 */
function puppetResponseEvidence(before: Session, after: Session, actorId: string): {
  targetId: string | null;
  ambiguous: boolean;
  stimulus: string;
} {
  const previousIds = new Set((before.facts || []).map((f) => f.id));
  const committed = (after.facts || []).filter((f) =>
    f.turn === after.turnIndex &&
    f.actorId === actorId &&
    f.validated === true &&
    (f.kind === "speech" || f.kind === "action") &&
    !previousIds.has(f.id),
  );
  const speechTargets = [...new Set(committed.filter((f) => f.kind === "speech" && f.targetId).map((f) => f.targetId!))];
  const actionTargets = [...new Set(committed.filter((f) => f.kind === "action" && f.targetId).map((f) => f.targetId!))];
  const candidates = speechTargets.length ? speechTargets : actionTargets;
  return {
    targetId: candidates.length === 1 ? candidates[0] : null,
    ambiguous: candidates.length > 1,
    stimulus: committed.map((f) => f.text).filter(Boolean).join("\n"),
  };
}

function hintsFromPrepare(ctx: Record<string, unknown> | undefined): string[] {
  if (!ctx) return [];
  const bag: unknown[] = [];
  if (Array.isArray(ctx.triggerHints)) bag.push(...ctx.triggerHints);
  const spiegel = ctx.spiegel as { triggerHints?: unknown; cues?: unknown } | undefined;
  if (Array.isArray(spiegel?.triggerHints)) bag.push(...spiegel.triggerHints);
  if (Array.isArray(ctx.cues)) bag.push(...ctx.cues);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const h of bag) {
    let s = "";
    if (typeof h === "string") s = h;
    else if (h && typeof h === "object") {
      const rec = h as { effectText?: unknown; text?: unknown; match?: unknown };
      s = String(rec.effectText || rec.text || rec.match || "");
    }
    const t = s.trim();
    if (t && !seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out;
}

const ROLES: { id: SpeakerMode; label: string }[] = [
  { id: "beobachter", label: "Beobachter" },
  { id: "teilnehmer", label: "Teilnehmer" },
  { id: "avatar", label: "Avatar" },
  { id: "puppet", label: "Puppet" },
  { id: "regie", label: "Regisseur" },
  { id: "god", label: "Gott" },
];

export function ChatPage() {
  const { sessionId } = Route.useParams();
  const hydrated = useHydrated();
  const sessions = useMatrix((s) => s.sessions);
  const worlds = useMatrix((s) => s.worlds);
  const characters = useMatrix((s) => s.characters);
  const snapshots = useMatrix((s) => s.snapshots);
  const triggers = useMatrix((s) => s.triggers);
  const saveSession = useMatrix((s) => s.saveSession);
  const addCharacter = useMatrix((s) => s.addCharacter);
  const patchCharacter = useMatrix((s) => s.patchCharacter);
  const acceptKernelSession = useMatrix((s) => s.acceptKernelSession);
  const setSpiegelStore = useMatrix((s) => s.setSpiegel);
  const setActiveSession = useMatrix((s) => s.setActiveSession);
  const addSnapshot = useMatrix((s) => s.addSnapshot);
  const restoreSnapshot = useMatrix((s) => s.restoreSnapshot);
  const addUpload = useMatrix((s) => s.addUpload);
  const commitUpload = useMatrix((s) => s.commitUpload);
  const uploads = useMatrix((s) => s.uploads);
  const log = useMatrix((s) => s.log);
  const patchUser = useMatrix((s) => s.patchUser);
  const config = useMatrix((s) => s.config);
  const activeUserId = useMatrix((s) => s.activeUserId);
  const users = useMatrix((s) => s.users);
  const user = users.find((u) => u.id === activeUserId);

  const session = sessions.find((x) => x.id === sessionId);
  const world = worlds.find((w) => w.id === session?.worldId);
  const worldChars = useMemo(
    () => (session ? characters.filter((c) => c.worldId === session.worldId) : []),
    [characters, session],
  );
  const natives = useMemo(() => worldChars.filter((c) => c.isWorldNative), [worldChars]);

  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  // V92 Paket 16 (Paket-15-Pruefung): the server's identity question for the last input - answered here, then the SAME input is sent again
  const [klaerung, setKlaerung] = useState<{ msg: string; fragen: KlaerungFrage[]; antworten: KlaerungAntwort[] } | null>(null);
  const hintSeenRef = useRef<string>("");
  // V65U (Plan U4/U5; Codegutachten v1 UI-Befund): the open input waiting for its answer, read from the STORED session
  // state (GET /api/sessions/:id -> pendingInput, never stored itself) - shown after reload too.
  const [pendingView, setPendingView] = useState<PendingInputView | null>(null);
  const refreshPending = useCallback(async () => {
    try {
      const got = (await apiGetSession(sessionId)) as { session?: Session & { pendingInput?: PendingInputView | null } };
      if (got?.session) {
        // P23: "Status neu prüfen" must also rehydrate the visible timeline.
        // Hiding a pending banner alone would leave a committed answer invisible.
        acceptKernelSession(got.session);
        setPendingView(got.session.pendingInput ?? null);
      }
    } catch {
      /* the banner only mirrors stored state; a failed read shows nothing new */
    }
  }, [sessionId, acceptKernelSession]);
  useEffect(() => {
    void refreshPending();
  }, [refreshPending]);
  const [fires, setFires] = useState<SynapseFire[]>([]);
  // V92 Paket 14 (Paket-13-Pruefung, Entscheidung 4; AMASTER §27.2 "Ob er über einen Avatar spricht oder außerhalb der Welt
  // bleibt, wird ausdrücklich gebunden"): the speaker binding is the one the user chose, stored in the session (session owner,
  // field speakAs) and read back after a reload. Before, it was derived once from the not-yet-loaded session and fell back to
  // "Bedienperson" unnoticed. Without a valid stored binding nothing is written until the user chooses again.
  const speakerAs = boundSpeakAs(session, natives);
  const [targetId, setTargetId] = useState("");
  const [godScope, setGodScope] = useState<GodScope>("auto");
  // V65Y (Gesamtpruefung V65X N06; AMASTER §20/§46.5): the director's explicit scene transition for THIS instruction
  const [szenenUebergang, setSzenenUebergang] = useState<"neue_szene" | "szene_endet" | "keiner">("keiner");
  const [regieActorId, setRegieActorId] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadMode, setUploadMode] = useState<UploadMode>("B");
  const [debug, setDebug] = useState(false);
  const [triggerHints, setTriggerHints] = useState<string[]>([]);
  const [newAvatarName, setNewAvatarName] = useState("");
  const [avatarErr, setAvatarErr] = useState<string | null>(null);
  const [pendingSpeech, setPendingSpeech] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  // V25.1 (AMASTERv2 §56/§61): Rollen, Sprecher-/Puppet-Wahl, Ziel, Regie, Gott, Fate sind
  // sichtbar bedienbar — Steuerung standardmäßig offen, kein verstecktes Mini-Menü.
  const [regieOpen, setRegieOpen] = useState(true);
  const [perceptionOpen, setPerceptionOpen] = useState(false);
  const [llmNotice, setLlmNotice] = useState("");
  const [speakerPick, setSpeakerPick] = useState<Array<{ id: string; name?: string; score: number; reasons?: string[] }>>([]);
  const [recording, setRecording] = useState(false);
  const recRef = useRef<SpeechRecognition | null>(null);
  const autoTimer = useRef<number | null>(null);
  // A pending timer alone is not the whole chain: an async gate or model call
  // may already be running when Stop or a new user turn is requested.
  const autoChainEpoch = useRef(0);
  useEffect(() => () => {
    autoChainEpoch.current += 1;
    if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
    autoTimer.current = null;
  }, []);
  // One pending tap per figure; distinct figures remain selectable and their
  // writes are serialized by the existing canonical kernel-bridge path.
  const [presencePending, setPresencePending] = useState<string[]>([]);
  const presencePendingRef = useRef(new Set<string>());

  useEffect(() => {
    if (sessionId) setActiveSession(sessionId);
  }, [sessionId, setActiveSession]);

  useEffect(() => {
    if (!hydrated) return;
    if (activeUserId && session && world) return;
    if (!readStoredActor()) return;
    void rebindStoredActor().catch(() => undefined);
  }, [hydrated, activeUserId, session, world]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: 99999 });
  }, [session?.turns.length, pendingSpeech, busy]);

  useEffect(() => {
    if (!session) {
      setTargetId("");
      return;
    }
    const eligible = worldChars.filter((c) => c.isWorldNative &&
      c.id !== session.avatarId && session.scene.presentIds.includes(c.id));
    // A left/deleted figure cannot remain selected invisibly in a <select>.
    // Multiple candidates remain an explicit user choice, never guessed.
    if (targetId && eligible.some((c) => c.id === targetId)) return;
    const next = eligible.length === 1 ? eligible[0].id : "";
    if (next !== targetId) setTargetId(next);
  }, [sessionId, session?.scene.presentIds, session?.avatarId, worldChars, targetId]);

  if (!hydrated) {
    return (
      <Shell title="Chat">
        <p className="text-sm text-muted">Lädt…</p>
      </Shell>
    );
  }
  if (!session || !world) {
    const stored = readStoredActor();
    if (!activeUserId && stored) {
      return (
        <Shell title="Chat">
          <p className="text-sm text-muted">Lädt kanonischen Stand…</p>
        </Shell>
      );
    }
    const needsActor = !activeUserId;
    return (
      <Shell title="Chat">
        <p className="text-sm text-muted">{needsActor ? "Kein aktiver User. Bitte zuerst einen User wählen." : "Session nicht gefunden."}</p>
        <Link to={needsActor ? "/user" : "/chat"} className="mt-3 inline-block text-accent">
          {needsActor ? "Zur Userwahl" : "Zur Sessionwahl"}
        </Link>
      </Shell>
    );
  }

  const present = worldChars.filter((c) => session.scene.presentIds.includes(c.id));
  const avatar = worldChars.find((c) => c.id === session.avatarId);
  const targetChar = worldChars.find((c) => c.id === targetId && session.scene.presentIds.includes(c.id));
  const mode = session.role;
  const writeLocked = busy || !speakerAs;
  function setSpeakerAs(v: string) {
    saveSession({ ...s, speakAs: v || null });
  }
  const s = session;
  const w = world;

  function setRole(role: SpeakerMode) {
    // V92 Paket 14: role and the speaker binding the user chooses with it are stored together (one save, no stale overwrite)
    const speakAs =
      role === "regie" ? "regie"
      : role === "god" ? "gott"
      : role === "teilnehmer" ? (s.avatarId ? "avatar" : "operator")
      : role === "avatar" ? "avatar"
      : role === "puppet" ? (natives[0] ? `char:${natives[0].id}` : "operator")
      : role === "beobachter" ? "observer"
      : s.speakAs ?? null;
    saveSession({ ...s, role, speakAs });
  }

  function patchPerception(kind: "hearsIds" | "seesIds", next: string[], explicit = true) {
    void kernelPerception({ session: s, kind, ids: next, explicit })
      .then(({ session: nextSession, trace }) => applyKernel(nextSession, trace))
      .catch((e) => setError(e instanceof Error ? e.message : "Wahrnehmung fehlgeschlagen"));
  }

  function togglePerception(kind: "hearsIds" | "seesIds", id: string) {
    const cur = s.scene[kind];
    const base = cur === undefined ? [...s.scene.presentIds] : [...cur];
    patchPerception(kind, base.includes(id) ? base.filter((x) => x !== id) : [...base, id]);
  }

  function patchPipeline(key: keyof typeof s.pipeline, v: boolean) {
    if (key === "fate") {
      void kernelFate({ session: s, enabled: v }).then(({ session, trace }) => applyKernel(session, trace)).catch((e) => {
        setError(e instanceof Error ? e.message : "Fate fehlgeschlagen");
      });
      return;
    }
    saveSession({ ...s, pipeline: { ...s.pipeline, [key]: v } });
  }

  function togglePresence(characterId: string) {
    if (presencePendingRef.current.has(characterId)) return;
    const current = useMatrix.getState().sessions.find((x) => x.id === sessionId);
    if (!current) {
      setError("Session nicht gefunden – Anwesenheit konnte nicht geschaltet werden.");
      return;
    }
    presencePendingRef.current.add(characterId);
    setPresencePending([...presencePendingRef.current]);
    void kernelPresence({ session: current, characterId })
      .then(({ session: next, trace }) => applyKernel(next, trace))
      .catch((e) => setError(e instanceof Error ? e.message : "Anwesenheit fehlgeschlagen"))
      .finally(() => {
        presencePendingRef.current.delete(characterId);
        setPresencePending([...presencePendingRef.current]);
      });
  }

  function applyKernel(session: Session, trace: KernelTrace) {
    acceptKernelSession(session);
    // V92: nicht zugeordnete Eingabeteile sichtbar machen (nur neue Hinweise, kein Dauerbanner)
    const h = eingabeHinweis(session);
    if (h && h.id !== hintSeenRef.current) {
      hintSeenRef.current = h.id;
      setHint(h.text);
    } else if (!h) {
      setHint(null);
    }
    log({
      level: "info",
      code: "KERNEL_WRITE",
      message: `${trace.writePath} turn=${trace.storeTurn} facts=${trace.storeFacts}`,
      sessionId,
      turn: trace.storeTurn,
    });
    log({
      level: trace.readOk ? "info" : "warn",
      code: "KERNEL_READ",
      message: trace.readOk
        ? `GET /api/sessions/${sessionId} turn=${trace.readTurn} facts=${trace.readFacts}`
        : `GET /api/sessions/${sessionId} failed after kernel write`,
      sessionId,
      turn: trace.readTurn ?? undefined,
    });
  }

  // V65F (AMASTER §27.2 "Ob er über einen Avatar spricht oder außerhalb der Welt bleibt, wird ausdrücklich
  // gebunden", §23): a follow-up turn keeps the participant binding the user chose. Before, every follow-up
  // was bound to the avatar whenever the session had one (session 05:33: Mara's turn after Clara's puppet line
  // ran with input actor Alrik — not present, not chosen; the user spoke as Bedienperson).
  const followAs = (s: { avatarId?: string | null }) =>
    speakerAs === "operator" || (speakerAs === "avatar" && s.avatarId) ? speakerAs : s.avatarId ? "avatar" : "operator";

  async function runFigure(speaker: StammCharacter, stimulus: string, userSpeech?: string, userName?: string, extra?: { inputKind?: string; speakAs?: string; roleOverride?: string; targetIdOverride?: string; autoPick?: boolean; directive?: string; resumePendingId?: string; klaerungen?: KlaerungAntwort[] }): Promise<boolean> {
    const liveRaw = useMatrix.getState().sessions.find((x) => x.id === sessionId);
    if (!liveRaw || !world) return false;
    if (!speakerAs) {
      // V92 Paket 14: no chosen speaker binding (e.g. after a reload of an older session) - nothing is written
      setError("Bitte zuerst unter „Spreche als“ wählen, wie du sprichst. Bis dahin wird nichts gespeichert.");
      return false;
    }
    let ok = false;
    let commitSourceTurnId: string | null = null;
    let commitFigureId: string | null = null;
    // Reaktionsturns (AutoChat, Antwort auf Puppet) laufen als normaler Figurenturn, nicht über
    // die Sonderautoritäten puppet/regie/god (deren Prepare weist 409 SPECIAL_AUTHORITY_ROUTE_REQUIRED zurück).
    const live = extra?.roleOverride ? { ...liveRaw, role: extra.roleOverride as Session["role"] } : liveRaw;
    setBusy(true);
    try {
      const prepared = await kernelPrepare({
        session: live,
        speaker,
        present,
        stimulus,
        userSpeech,
        userName,
        targetId: extra?.targetIdOverride ?? targetChar?.id ?? undefined,
        speakAs: extra?.speakAs ?? speakerAs,
        inputKind: extra?.inputKind,
        autoPick: extra?.autoPick,
        directive: extra?.directive,
        resumePendingId: extra?.resumePendingId,
        klaerungen: extra?.klaerungen,
      });
      if (prepared.speakerCandidates?.length) setSpeakerPick(prepared.speakerCandidates);
      const serverSpeakerId = String(prepared.truth.speaker_id || prepared.truth.speakerId || speaker.id);
      const commitSpeaker =
        serverSpeakerId === speaker.id ? speaker : natives.find((c) => c.id === serverSpeakerId) ?? speaker;
      const serverCtx = prepared.brainContext;
      const serverSpiegel = (serverCtx?.spiegel ?? null) as Spiegel | null;
      if (!serverCtx || !serverSpiegel) {
        setError("Prepare lieferte keinen Server-BrainContext.");
        log({ level: "error", code: "BRAIN_CONTEXT_MISSING", message: "kernelPrepare ohne brainContext.spiegel", sessionId: live.id });
        return false;
      }
      const fired = (serverSpiegel.fired || []) as SynapseFire[];
      setFires(fired);
      setSpiegelStore(JSON.stringify(serverSpiegel));
      setTriggerHints(hintsFromPrepare(serverCtx as Record<string, unknown>));
      const payload = {
        spiegel: serverSpiegel,
        sessionId: prepared.session.id,
        sourceTurnId: prepared.truth.id,
        speakerId: commitSpeaker.id,
        turnBeleg: prepared.turnBeleg,
        turnIndex: prepared.session.turnIndex,
        traceId: prepared.traceId,
        temperature: config.temperature,
        maxTokens: Math.min(config.maxTokens, 1024),
        model: user?.providerConfig?.model || config.model || "",
        endpoint: user?.providerConfig?.endpoint,
        text: userSpeech,
        scope: config.scope || "user",
        scopeId: config.scopeId,
        inputKind: extra?.inputKind || "speech",
        provider: config.provider || "openai",
      };
      let formulated: FormulateResult | null = null;
      let formulierungsBeleg: string | undefined;
      let formulateOk = true;
      let formulateError = "";
      let formulateSource = "synapse";
      let lastFormulateError = "";
      try {
        const raw = await apiFormulate(payload, { timeoutMs: 60000 });
        lastFormulateError = raw.llmError ? String(raw.llmError) : "";
        if (raw.ok === false) {
          formulateOk = false;
          formulateError = String(raw.message || raw.error || "Formulierung fehlgeschlagen");
        } else {
          const res = (raw.result as FormulateResult | undefined) || {
            speech: String(raw.speech || ""),
            action: raw.action ? String(raw.action) : null,
            source: (raw.source as FormulateResult["source"]) || "synapse",
          };
          if (raw.proposals && typeof raw.proposals === "object") res.proposals = raw.proposals as Record<string, unknown>;
          formulated = res;
          formulierungsBeleg = typeof raw.formulierungsBeleg === "string" ? raw.formulierungsBeleg : undefined;
          formulateSource = String(res.source || raw.source || "synapse");
        }
      } catch (e) {
        formulateOk = false;
        formulateError = e instanceof Error ? e.message : "Formulierung fehlgeschlagen";
      }
      if (!formulated) {
        throw new Error(formulateError || "Keine Modellantwort. Eingabe gespeichert; denselben Text zum Wiederholen senden.");
      }
      // V25.1 (AMASTERv2 §65): kein stiller Fallback. Wenn LLM gewünscht war, aber die
      // Antwort aus der lokalen Synapse kam, wird der Grund sichtbar gemeldet.
      if (formulateSource !== "llm" && config.llmEnabled !== false && (config.provider || "openai") !== "synapse") {
        setLlmNotice(`Kein LLM-Text: Antwort kam aus der lokalen Synapse. Grund: ${formulateError || String((lastFormulateError as string) || "Provider nicht erreichbar oder kein API-Key (Konfiguration → Sprachdienst → „Provider live prüfen“).")}`);
      } else {
        setLlmNotice("");
      }
      // Needed only to reconcile a timed-out mutating POST against canonical SQL.
      commitSourceTurnId = String(prepared.truth.id || "") || null;
      commitFigureId = commitSpeaker.id;
      const { session: committed, trace } = await kernelCommitFigure({
        session: prepared.session,
        speaker: commitSpeaker,
        present,
        result: formulated,
        fired,
        recallCount: Array.isArray(serverSpiegel.memories) ? serverSpiegel.memories.length : undefined,
        contradictions: Array.isArray((serverSpiegel as { contradictions?: unknown[] }).contradictions) ? (serverSpiegel as { contradictions?: unknown[] }).contradictions : undefined,
        userSpeech,
        userName,
        truth: prepared.truth,
        traceId: prepared.traceId,
        turnBeleg: prepared.turnBeleg,
        formulierungsBeleg,
      });
      applyKernel(committed, trace);
      // V35 (§65): Ein Turn ohne sichtbare neue Figurenzeile ist ein Fehler, keine stille Lücke.
      const lastLine = committed.turns.at(-1);
      const figureExecuted = Boolean(lastLine && lastLine.speakerId === commitSpeaker.id &&
        lastLine.turn === committed.turnIndex &&
        !(live.turns || []).some((previous: { id?: string }) => previous.id === lastLine.id) &&
        (((lastLine.speech || "").trim() !== "—" && Boolean((lastLine.speech || "").trim())) || lastLine.action));
      if (!figureExecuted) {
        setError(`${commitSpeaker.name} hat keine Zeile erzeugt (Commit ohne Rede/Handlung). Provider-Antwort: ${formulateSource}${formulateError ? ` · ${formulateError}` : ""}.`);
        log({ level: "error", code: "TURN_WITHOUT_LINE", message: `${commitSpeaker.name}: source=${formulateSource} ${formulateError || ""}`.trim(), sessionId: live.id, turn: committed.turnIndex });
      } else {
        log({ level: "info", code: "TURN_LINE", message: `${lastLine?.speakerName}: ${String(lastLine?.speech || lastLine?.action || "").slice(0, 80)} (${formulateSource})`, sessionId: live.id, turn: committed.turnIndex });
      }
      const blocked = committed.facts.slice(-3).find((f) => f.rejectionReason === "capability");
      if (blocked) {
        setError(`Capability: ${blocked.text || "Handlung/Rede nicht möglich."}`);
      }
      if (formulateSource !== "llm") {
        log({ level: "warn", code: "SYNAPSE_LOCAL", message: formulateError || "Flask-Formulate Synapse", sessionId: live.id, turn: committed.turnIndex });
      }
      if (user?.tts) {
        void speakNow(formulated.speech);
      }
      // Ein als 200 gespeicherter Turn ohne tatsächliche Figurenzeile
      // erfüllt §1 nicht und darf keine automatische Folgekette auslösen.
      ok = figureExecuted;
    } catch (e) {
      const timeoutCode = String((e as { code?: string } | null)?.code || "");
      if (timeoutCode === "KERNEL_COMMIT_STATUS_UNGEWISS" && commitSourceTurnId) {
        // A browser timeout is NOT a server rollback. Try an independent
        // SQL-backed read without retrying this potentially committed input.
        // Even when no matching Fact is visible yet, the server may be running.
        try {
          const checked = await apiGetSession(live.id, { timeoutMs: 12000 });
          if (checked.ok && checked.session) {
            const canonical = checked.session as unknown as Session;
            acceptKernelSession(canonical);
            const status = responseReadbackStatus(canonical, commitSourceTurnId, commitFigureId || "");
            const written = status === "antwort_gespeichert";
            setPendingView((canonical as Session & { pendingInput?: PendingInputView | null }).pendingInput ?? null);
            setError(written
              ? "Figurenantwort nach Zeitüberschreitung durch Turn, validierten Figuren-Fact und abgeschlossene Eingabe in SQLite nachgewiesen. Automatische Folge angehalten."
              : "Zeitüberschreitung: Die Antwort ist NICHT nachgewiesen (Eingabe-Facts zählen nicht). Status ungewiss; bitte den angezeigten offenen Eingabezug prüfen. Kein automatisches erneutes Senden.");
            log({ level: "warn", code: "KERNEL_COMMIT_TIMEOUT_READBACK", message: status, sessionId: live.id });
            return false;
          }
        } catch {
          /* Readback may fail too: outcome remains unknown, never retry automatically. */
        }
      }
      if (timeoutCode === "KERNEL_PREPARE_STATUS_UNGEWISS") {
        // P23: Prepare itself may have committed the input before its HTTP
        // response timed out. Never blindly POST it again. Only display the
        // canonical pending input and the existing resume/close controls.
        try {
          const checked = await apiGetSession(live.id, { timeoutMs: 12000 });
          if (checked.ok && checked.session) {
            const canonical = checked.session as unknown as Session & { pendingInput?: PendingInputView | null };
            acceptKernelSession(canonical);
            setPendingView(canonical.pendingInput ?? null);
            setError(canonical.pendingInput
              ? "Prepare-Zeitüberschreitung: eine offene Eingabe liegt im Serverzustand. Unten kannst du ihren Text und den Antwortversuch prüfen; keine automatische Doppelsendung."
              : "Prepare-Zeitüberschreitung: im gerade gelesenen Serverstand keine offene Eingabe. Der ursprüngliche Versuch kann noch laufen. Status UNGEWISS; nicht erneut senden, bevor der Zustand geklärt ist.");
            log({ level: "warn", code: "KERNEL_PREPARE_TIMEOUT_READBACK", message: canonical.pendingInput ? "offene_eingabe" : "ungewiss", sessionId: live.id });
            return false;
          }
        } catch { /* readback failed - prepare's server result remains unknown */ }
        setError("Prepare-Zeitüberschreitung, Serverzustand nicht lesbar: Status UNGEWISS. Keine automatische Wiederholung. Bitte den Sessionstand prüfen.");
        return false;
      }
      const msg = e instanceof Error ? e.message : "Kernel-Commit fehlgeschlagen";
      // V92 Paket 9: eine abgelehnte Avatar-Eingabe zeigt die Begründung des Servers ohne technischen Präfix
      setError(planIncompleteMeldung(msg) ?? msg);
      // V92 Paket 16: a name the server cannot prove - the question is shown below the input with the candidate figures
      const fragen = identitaetsKlaerung(e);
      if (fragen && userSpeech) setKlaerung({ msg: userSpeech, fragen, antworten: extra?.klaerungen ?? [] });
      log({ level: "error", code: "KERNEL_FAILED", message: msg, sessionId: live.id });
    } finally {
      setBusy(false);
      setPendingSpeech("");
      void refreshPending();
    }
    return ok;
  }

  function cancelAutoChain() {
    autoChainEpoch.current += 1;
    if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
    autoTimer.current = null;
  }

  // V65U (Codegutachten v1 UI-Befund): a failed send never loses what the user typed - restored unless a new text is in the field.
  const restoreText = (msg: string) => setText((cur) => (cur.trim() ? cur : msg));

  // V65U (Plan U4 "Antwort erneut erzeugen"): the SAME stored input again (resumePending), answered by its target figure.
  async function resumePending(view: PendingInputView) {
    const live = useMatrix.getState().sessions.find((x: Session) => x.id === sessionId);
    if (!live || !world || writeLocked) return;
    if (!canExplicitlyRetryPendingAttempt(view)) {
      setError("Der frühere Antwortversuch läuft nachweislich noch. Ein gleichzeitiger zweiter Schreibversuch ist gesperrt.");
      return;
    }
    // V65W/P24: an unprovable old process may have stopped forever. Only an
    // EXPLICIT UI click retries the same open TurnTruth. The first SQLite
    // commit wins; no timer, refresh, or automatic double submission here.
    // The stored TurnTruth owns the answer speaker. targetId is the
    // ADDRESSEE of the input, not authority to swap its answer actor.
    const responder = natives.find((c: StammCharacter) => c.id === view.speakerId) ?? null;
    if (!responder) {
      setError("Die wartende Eingabe hat keinen kanonisch gebundenen Antwortsprecher in dieser Welt. Keine Ersatzfigur.");
      return;
    }
    setError(null);
    await runFigure(responder, view.text, view.text, live.alias || avatar?.name || user?.name,
      { speakAs: followAs(live), targetIdOverride: view.targetId ?? undefined, resumePendingId: view.turnTruthId });
  }

  async function closePending(view: PendingInputView) {
    const r = await fetch("/api/kernel/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...actorHeader() },
      body: JSON.stringify({ sessionId, closePending: { turnTruthId: view.turnTruthId } }),
    });
    const j = (await r.json().catch(() => ({}))) as { code?: string; message?: string };
    if (r.ok) location.reload();
    else setError(`Eingabe nicht abgeschlossen: ${j.message || j.code || r.status}`);
  }

  async function send(overrideText?: string, klaerungen?: KlaerungAntwort[]) {
    const live = useMatrix.getState().sessions.find((x) => x.id === sessionId);
    if (!live || !world || writeLocked) return;
    const msg = (overrideText ?? text).trim();
    if (!msg) return;
    setKlaerung(null);
    // User input supersedes old automatic continuations. In-flight callbacks
    // cannot create a later follow-up from a superseded chain.
    cancelAutoChain();
    setError(null);
    setPendingSpeech(msg);
    setText("");

    if (speakerAs === "gott" || live.role === "god") {
      setBusy(true);
      let godApplied = false;
      try {
        const godRes = await kernelGod({
          session: live,
          text: msg,
          scope: godScope,
          targetId: targetId || undefined,
          otherId: godScope === "relationship" ? live.avatarId || undefined : undefined,
          szenenuebergang: szenenUebergang,
        });
        setSzenenUebergang("keiner");
        const { session: next, trace } = godRes;
        applyKernel(next, trace);
        {
          const applied = (godRes as { applied?: Array<{ art?: string; target?: string; other?: string; text?: string; applied?: boolean }> }).applied || [];
          const unclear = (godRes as { unclear?: Array<{ text?: string; grund?: string }> }).unclear || [];
          const executed = applied.filter((a) => a.applied === true);
          const rejected = applied.filter((a) => a.applied !== true);
          if (applied.length || unclear.length) {
            setError(`Gott: ${executed.length} tatsächlich angewendet, ${rejected.length + unclear.length} nicht angewendet` +
              (executed.length ? ` · Vollzogen: ${executed.map((a) => `${a.art}${a.target ? " " + a.target : ""}${a.other ? "→" + a.other : ""}`).join(", ")}` : "") +
              (rejected.length ? ` · ABGELEHNT: ${rejected.map((a) => String(a.text || a.art || "").slice(0, 60)).join("; ")}` : "") +
              (unclear.length ? ` · UNKLAR: ${unclear.map((u) => `„${String(u.text || "").slice(0, 40)}“ (${u.grund})`).join("; ")}` : ""));
          }
          const lastGod = (next.godFacts || []).at(-1);
          godApplied = applied.length ? applied.some((a) => a.applied !== false) : Boolean(lastGod?.applied);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "God-Turn fehlgeschlagen");
        restoreText(msg);
      } finally {
        setBusy(false);
        setPendingSpeech("");
      }
      // V65E (AMASTER §28 Schritt 23, §27.8, §48, §46.6): God sets the fact and invents no
      // follow-up act; the scene goes on through the normal path — the kernel gate picks who
      // reacts (the figure the fact affected first), then AutoChat as configured.
      if (godApplied) queueAuto(live.autoChat.enabled ? live.autoChat.turns + 1 : 1, live.autoChat.delayMs, 0);
      return;
    }
    if (speakerAs === "regie" || live.role === "regie") {
      setBusy(true);
      try {
        const { session: next, trace } = await kernelRegie({
          session: live,
          world,
          text: msg,
          targetId: targetId || undefined,
          actorId: regieActorId || undefined,
          present,
          directAction: (document.getElementById("matrix-regie-direct") as HTMLInputElement | null)?.checked === true,
          szenenuebergang: szenenUebergang,
        });
        setSzenenUebergang("keiner");
        applyKernel(next, trace);
        // V46 (AMASTERv2 §27.6): Eine Anweisung an eine Figur wird von der Figur UMGESETZT —
        // LLM-Turn mit verbindlicher Anweisung, in ihrem Ton; Körperanweisungen wirkten bereits im Commit.
        const lastRegie = [...next.turns].reverse().find((t) => t.role === "regie") as { directiveFor?: string; directiveText?: string; regieEffects?: { executed?: Array<{ validated?: boolean; rejection?: string | null }>; speech?: Array<{ segment?: string; inhalt?: string }>; unclear?: Array<{ grund?: string }> } } | undefined;
        const actorId = lastRegie?.directiveFor || regieActorId || "";
        const actor = actorId ? worldChars.find((c) => c.id === actorId) : undefined;
        // V65E (AMASTER §27.5/§46.6, §28 Schritt 23, §48): a Regie that only orders acts is done
        // when they are committed — no ordered speech for the actor. The scene goes on through
        // the kernel gate (the affected figure first), not as a forced second turn of the actor.
        const regieActsOnly = Boolean(lastRegie?.regieEffects && (lastRegie.regieEffects.executed || []).some((x) => x.validated) && !(lastRegie.regieEffects.speech || []).length);
        // V65J (AMASTER §24.7, §46.6; Prüfbericht v2.2 Kette D): the reading bound nothing
        // executable and no speech - nothing happened. No figure gets the raw text as an
        // order (before: the else branch forced the chosen figure to formulate it).
        const regieUnclear = Boolean(lastRegie?.regieEffects && !(lastRegie.regieEffects.executed || []).some((x) => x.validated) && !(lastRegie.regieEffects.speech || []).length);
        // V65Y (N06): the director's explicit scene transition happened even when the text ordered no figure act
        const regieUebergang = (lastRegie?.regieEffects as { uebergang?: string } | undefined)?.uebergang;
        if (regieUebergang && regieUnclear) {
          setBusy(false);
          setError(regieUebergang === "neue_szene" ? "Regie: neue Szene begonnen (Auswahl). Keine Figurenhandlung angeordnet." : "Regie: Szene beendet (Auswahl). Keine Figurenhandlung angeordnet.");
        } else if (regieActsOnly) {
          setBusy(false);
          queueAuto(live.autoChat.enabled ? live.autoChat.turns + 1 : 1, live.autoChat.delayMs, 0);
        } else if (regieUnclear) {
          setBusy(false);
          const why = [...(lastRegie?.regieEffects?.unclear || []).map((u) => String(u.grund || "")), ...(lastRegie?.regieEffects?.executed || []).filter((x) => !x.validated).map((x) => String(x.rejection || ""))].filter(Boolean).map((g) => g.replace(/_/g, " "));
          setError(`Regie nicht ausgeführt${why.length ? `: ${why.join("; ")}` : ""}. Nichts ist geschehen; bitte genauer anweisen.`);
        } else if (actor && actor.id !== next.avatarId) {
          // AMASTER §46.6 / SPS V65E: Der Körpervollzug ist bereits geschrieben.
          // Bei gemischter Regie (Tat + angeordnete Rede) darf die Figur nicht
          // den gesamten ursprünglichen Tatbefehl erneut ausführen. Nur der
          // bereits gebundene Redeauftrag gelangt in ihren normalen Figurenzug.
          const speechDirective = (lastRegie?.regieEffects?.speech || [])
            .map((entry) => String((entry as { segment?: string; inhalt?: string }).segment || (entry as { inhalt?: string }).inhalt || "").trim())
            .filter(Boolean).join(" und ");
          const actAlreadyWritten = (lastRegie?.regieEffects?.executed || []).some((entry) => entry.validated);
          const figureDirective = actAlreadyWritten && speechDirective ? speechDirective : msg;
          setBusy(false);
          const figureCommitted = await runFigure(actor, figureDirective, undefined, undefined, {
            inputKind: "autochat", speakAs: followAs(next), roleOverride: "teilnehmer",
            targetIdOverride: targetId && targetId !== actor.id ? targetId : undefined,
            directive: figureDirective,
          });
          // Die betroffene Figur hat auch bei AutoChat AUS einen Folgeturn.
          // Ein abgebrochener Täterturn startet dagegen keine fiktive Folge.
          if (figureCommitted) queueAuto(live.autoChat.enabled ? live.autoChat.turns : 1, live.autoChat.delayMs, 0);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Regie-Turn fehlgeschlagen");
        restoreText(msg);
      } finally {
        setBusy(false);
        setPendingSpeech("");
      }
      return;
    }
    if (speakerAs.startsWith("char:")) {
      const fig = natives.find((c) => c.id === speakerAs.slice(5));
      if (!fig) {
        setPendingSpeech("");
        return;
      }
      const figRt = live.runtimes[fig.id];
      const speakOk = canPerform(figRt, "move", true);
      if (!speakOk.ok) {
        setError(`Capability: ${fig.name} ${speakOk.reason}. Rede wird nicht als Wahrheit geschrieben.`);
      }
      setBusy(true);
      let puppetNext: Session | null = null;
      try {
        const { session: next, trace } = await kernelPuppet({ session: live, figure: fig, text: msg, klaerungen });
        applyKernel(next, trace);
        // A successful HTTP/SQLite write is not proof that this figure spoke
        // or acted. The gagged/capability-blocked placeholder '—' is not an
        // executed turn and must not generate a fabricated witness response.
        const puppetCommitted = next.turns.some((t) =>
          t.turn === next.turnIndex && t.speakerId === fig.id &&
          !(live.turns || []).some((previous: { id?: string }) => previous.id === t.id) &&
          (((t.speech || "").trim() !== "—" && Boolean((t.speech || "").trim())) || Boolean(t.action))
        );
        puppetNext = puppetCommitted ? next : null;
        if (!puppetCommitted) setError("Puppet: Keine Rede oder Handlung vollzogen. Kein Folgezug gestartet.");
        const blocked = next.facts.slice(-3).find((f) => f.rejectionReason === "capability");
        if (blocked) setError(`Capability: ${blocked.text || speakOk.reason || "blockiert"}`);
      } catch (e) {
        const msgText = e instanceof Error ? e.message : "";
        setError(planIncompleteMeldung(msgText) ?? (msgText || "Puppet-Turn fehlgeschlagen"));
        restoreText(msg);
        const fragen = identitaetsKlaerung(e);
        if (fragen) setKlaerung({ msg, fragen, antworten: klaerungen ?? [] });
      } finally {
        setBusy(false);
        setPendingSpeech("");
      }
      // V35 (AMASTERv2 §27.4/§28, Nutzerbefund "Puppet: nirgends eine Antwort"): Die Szene reagiert
      // auf die gesteuerte Figur wie auf den Avatar — die angesprochene bzw. gewählte Figur antwortet.
      if (puppetNext) {
        const scenePresent = worldChars.filter((c) => puppetNext!.scene.presentIds.includes(c.id) && c.isWorldNative && c.id !== fig.id && c.id !== puppetNext!.avatarId);
        // Der Server-Fact bestimmt den Adressaten. UI-Auswahl und Rohtext sind keine Wahrheit.
        const evidence = puppetResponseEvidence(live, puppetNext, fig.id);
        if (!evidence.stimulus) {
          setError("Puppet: Keine bestätigte Rede oder Handlung als Anlass gespeichert. Kein Folgezug.");
          return;
        }
        if (evidence.ambiguous) {
          setError("Puppet: Mehrere kanonische Adressaten. Keine willkürliche Antwortfigur gewählt.");
          return;
        }
        let responder = evidence.targetId ? scenePresent.find((c) => c.id === evidence.targetId) : undefined;
        if (evidence.targetId && !responder) {
          setError("Puppet: Der bestätigte Adressat ist nicht in der Szene. Kein fremder Ersatzsprecher.");
          return;
        }
        if (!responder) {
          // Für nicht adressierte Ereignisse entscheidet allein der kanonische Server-Gate.
          const gate = await kernelAutochatGate({ session: puppetNext, remaining: 1, stimulus: evidence.stimulus });
          if (!gate.stop && gate.speakerId) responder = scenePresent.find((c) => c.id === gate.speakerId);
        }
        if (responder) {
          // Der Folgezug liest die tatsächlich geschriebenen Facts, nicht den originalen Puppet-Rohtext.
          const responseCommitted = await runFigure(responder, evidence.stimulus, undefined, undefined, {
            inputKind: "autochat", speakAs: followAs(puppetNext), roleOverride: "teilnehmer",
            targetIdOverride: fig.id,
          });
          if (responseCommitted && live.autoChat.enabled) queueAuto(live.autoChat.turns, live.autoChat.delayMs);
        }
      }
      return;
    }

    if (live.role === "beobachter" || speakerAs === "observer") {
      const dummy = natives[0] || worldChars[0];
      if (!dummy) {
        setError("Keine Figur in der Welt für den Beobachter-Kontext.");
        setPendingSpeech("");
        return;
      }
      setBusy(true);
      try {
        const prepared = await kernelPrepare({
          session: { ...live, role: "beobachter" },
          speaker: dummy,
          present,
          stimulus: msg,
          userSpeech: msg,
          userName: live.alias || user?.name,
          targetId: targetId || undefined,
          speakAs: "observer",
          inputKind: "comment",
        });
        setTriggerHints(hintsFromPrepare(prepared.brainContext));
        const { session: next, trace } = await kernelCommitFigure({
          session: prepared.session,
          speaker: dummy,
          present,
          result: { speech: "", action: null },
          fired: [],
          userSpeech: msg,
          userName: live.alias || user?.name,
          truth: { ...prepared.truth, role: "beobachter", authority: "observer", inputKind: "comment", input_kind: "comment", inputActorId: "observer" },
          traceId: prepared.traceId,
          turnBeleg: prepared.turnBeleg,
        });
        applyKernel(next, trace);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Beobachter-Kommentar fehlgeschlagen");
      } finally {
        setBusy(false);
        setPendingSpeech("");
      }
      return;
    }

    // V35 (§65, Nutzerbefund "kein Avatar, nirgends eine Antwort"): jeder Sendeversuch wird protokolliert,
    // damit ein stiller Abbruch im Client nicht mehr unsichtbar bleibt.
    log({ level: "info", code: "UI_SEND", message: `mode=${speakerAs} role=${live.role} natives=${natives.length} present=${present.length} avatarPresent=${live.avatarId ? live.scene.presentIds.includes(live.avatarId) : false}`, sessionId: live.id, turn: live.turnIndex });
    let nativesNow = natives;
    let presentNow = present;
    // V35 (§22/§27.3): Wer als Avatar spricht, ist in der Szene. Fehlt der Avatar in presentIds
    // (ältere Sessions), wird seine Anwesenheit als kanonischer Presence-Fact gesetzt.
    if ((speakerAs === "avatar" || live.role === "avatar") && live.avatarId && !live.scene.presentIds.includes(live.avatarId)) {
      try {
        const { session: withAvatar, trace } = await kernelPresence({ session: live, characterId: live.avatarId });
        applyKernel(withAvatar, trace);
        presentNow = worldChars.filter((c) => withAvatar.scene.presentIds.includes(c.id));
      } catch (e) {
        log({ level: "warn", code: "AVATAR_PRESENCE_FAILED", message: e instanceof Error ? e.message : "presence", sessionId: live.id });
      }
    }
    if (!nativesNow.length) {
      // Figuren fehlen im Client-Speicher (veralteter Browserstand) → kanonischen Stand vom Server holen.
      try {
        const mcc = (await apiGetMcc()) as { characters?: StammCharacter[] };
        const chars = (mcc.characters || []).map(hydrateCharacter);
        if (chars.length) {
          useMatrix.setState({ characters: chars });
          nativesNow = chars.filter((c) => c.worldId === live.worldId && c.isWorldNative);
          presentNow = chars.filter((c) => c.worldId === live.worldId && live.scene.presentIds.includes(c.id));
        }
      } catch {
        /* unten sichtbar gemeldet */
      }
    }
    const presentNatives = presentNow.filter((c) => c.isWorldNative && c.id !== live.avatarId);
    const addressed = targetChar?.name ?? detectAddressed(msg, presentNatives, live);
    let speaker =
      pickSpeaker({ world, session: live, natives: presentNatives, stimulus: msg, explicitName: addressed, uiTargetId: targetChar?.id }) ||
      presentNatives[0];
    // A figure outside the SQL scene may not be summoned as a fallback.
    // Arrival requires a real presence/action event, not a frontend guess.
    if (!speaker) {
      const av = worldChars.find((c) => c.id === live.avatarId);
      const asAvatar = speakerAs === "avatar" || live.role === "avatar";
      if (asAvatar && av) {
        setBusy(true);
        try {
          const prepared = await kernelPrepare({
            session: live,
            speaker: av,
            present,
            stimulus: msg,
            userSpeech: msg,
            userName: live.alias || av.name || user?.name,
            targetId: targetId || undefined,
            speakAs: "avatar",
            inputKind: "speech",
            klaerungen,
          });
          const { session: next, trace } = await kernelCommitFigure({
            session: prepared.session,
            speaker: av,
            present,
            result: { speech: "", action: null },
            fired: [],
            userSpeech: msg,
            userName: live.alias || av.name || user?.name,
            truth: { ...prepared.truth, role: "avatar", authority: "avatar", inputKind: "speech", input_kind: "speech" },
            traceId: prepared.traceId,
            turnBeleg: prepared.turnBeleg,
          });
          applyKernel(next, trace);
          setError("Deine Avatar-Zeile ist gespeichert, aber keine Figur konnte antworten: keine Weltfigur in der Szene. Figur unter Anwesend setzen oder als Puppet holen.");
          log({ level: "warn", code: "AVATAR_LINE_WITHOUT_RESPONDER", message: "keine anwesende Weltfigur", sessionId: live.id, turn: live.turnIndex });
        } catch (e) {
          setError(e instanceof Error ? e.message : "Avatar-Turn fehlgeschlagen");
          restoreText(msg);
          const fragen = identitaetsKlaerung(e);
          if (fragen) setKlaerung({ msg, fragen, antworten: klaerungen ?? [] });
        } finally {
          setBusy(false);
          setPendingSpeech("");
        }
        return;
      }
      setError("Keine anwesende Figur (Avatar wird nie automatisch Sprecher). Figur unter Anwesend setzen oder als Puppet holen.");
      log({ level: "error", code: "NO_SPEAKER", message: `natives=${nativesNow.length} present=${presentNow.length}`, sessionId: live.id, turn: live.turnIndex });
      setPendingSpeech("");
      return;
    }
    const committed = await runFigure(speaker, msg, msg, live.alias || avatar?.name || user?.name, { speakAs: speakerAs, klaerungen });
    if (!committed) {
      restoreText(msg);
      return; // The failed input is not a valid cause for a new figure turn.
    }
    const liveNow = useMatrix.getState().sessions.find((x) => x.id === sessionId) || live;
    if (liveNow.autoChat.enabled) queueAuto(liveNow.autoChat.turns, liveNow.autoChat.delayMs);
    else log({ level: "info", code: "AUTOCHAT_SKIPPED", message: "AutoChat ist aus", sessionId: live.id, turn: live.turnIndex });
  }

  // V92 Paket 16: one answer to the server's identity question; when every question is answered, the SAME input goes again with them.
  // V92 Paket 17 (Paket-16-Prüfung A/B): each answer belongs to ONE question (its written place, the server's `frage`) - the same
  // name written twice is answered twice; the server accepts only answers to the questions it issued for this input.
  function klaere(frage: string, id: string | null) {
    if (!klaerung) return;
    const antworten = [...klaerung.antworten.filter((a) => a.frage !== frage), { frage, id }];
    if (klaerung.fragen.some((f) => !antworten.some((a) => a.frage === f.frage))) {
      setKlaerung({ ...klaerung, antworten });
      return;
    }
    const msg = klaerung.msg;
    setKlaerung(null);
    setText("");
    void send(msg, antworten);
  }

  function queueAuto(n: number, delay: number, firstDelay?: number, chainEpoch?: number) {
    // A newly started chain invalidates any earlier one. Recursive steps pass
    // their own epoch; no stale timer/gate/response may re-arm after Stop.
    if (chainEpoch === undefined) {
      cancelAutoChain();
      chainEpoch = autoChainEpoch.current;
    } else if (chainEpoch !== autoChainEpoch.current) {
      return;
    }
    if (n <= 0) return;
    if (autoTimer.current !== null) window.clearTimeout(autoTimer.current);
    const runEpoch = chainEpoch;
    log({ level: "info", code: "AUTOCHAT_QUEUED", message: `remaining=${n} delayMs=${delay}`, sessionId, turn: session.turnIndex });
    autoTimer.current = window.setTimeout(async () => {
      if (runEpoch !== autoChainEpoch.current) return;
      autoTimer.current = null;
      const live = useMatrix.getState().sessions.find((x) => x.id === sessionId);
      if (!live || !world) return;
      try {
        const gate = await kernelAutochatGate({
          session: live,
          remaining: n,
          stimulus: live.turns.at(-1)?.speech || "",
        });
        if (runEpoch !== autoChainEpoch.current) return;
        if (gate.stop) {
          log({ level: "info", code: "AUTOCHAT_STOP", message: gate.reason || "stop", sessionId: live.id });
          return;
        }
        const nextSpeaker = gate.speakerId ? natives.find((c) => c.id === gate.speakerId) : null;
        if (!nextSpeaker) {
          log({ level: "info", code: "AUTOCHAT_STOP", message: "no_speaker", sessionId: live.id });
          return;
        }
        if (Array.isArray((gate as { candidates?: unknown }).candidates)) setSpeakerPick((gate as { candidates: Array<{ id: string; name?: string; score: number; reasons?: string[] }> }).candidates);
        // The kernel decides the actual next speaker; never force the UI target.
        const committed = await runFigure(nextSpeaker, live.turns.at(-1)?.speech || "", undefined, undefined, { inputKind: "autochat", speakAs: followAs(live), roleOverride: ["puppet", "regie", "god"].includes(live.role) ? "teilnehmer" : undefined });
        if (runEpoch !== autoChainEpoch.current) return;
        if (!committed) {
          log({ level: "warn", code: "AUTOCHAT_STOP", message: "figure_turn_not_committed", sessionId: live.id });
          return;
        }
        queueAuto(n - 1, delay, undefined, runEpoch);
      } catch (e) {
        log({ level: "error", code: "AUTOCHAT_STOP", message: e instanceof Error ? e.message : "gate failed", sessionId: live.id });
      }
    }, firstDelay ?? delay);
  }

  async function speakNow(speech: string) {
    if (recRef.current) {
      try {
        recRef.current.stop();
      } catch {
        /* ignore */
      }
      recRef.current = null;
    }
    try {
      await apiSpeechTts({ text: speech, lang: "de-DE" });
    } catch {
      /* contract must not block device playback */
    }
    speak(speech);
  }

  function stop() {
    cancelAutoChain();
    setBusy(false);
    speechSynthesis.cancel();
  }

  async function mic() {
    if (typeof speechSynthesis !== "undefined" && speechSynthesis.speaking) {
      setError("STT pausiert während TTS.");
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setError("Spracheingabe nicht verfügbar (kein Gerät).");
      return;
    }
    if (recRef.current) {
      recRef.current.stop();
      recRef.current = null;
      setRecording(false);
      return;
    }
    const rec = new SR();
    rec.lang = "de-DE";
    void apiSpeechStt({ lang: "de-DE" }).catch(() => undefined);
    rec.onresult = (ev: SpeechRecognitionEvent) => {
      const t = ev.results[0]?.[0]?.transcript ?? "";
      if (user?.sttMode === "autosend") {
        setText("");
        void send(t);
      } else setText((prev) => `${prev} ${t}`.trim());
    };
    rec.onend = () => {
      recRef.current = null;
      setRecording(false);
    };
    recRef.current = rec;
    setRecording(true);
    rec.start();
  }

  async function onUploadFile(file: File, mode: UploadMode) {
    const extracted = await extractTextFromFile(file);
    const ocr = await textFromUpload({ text: extracted.text, dataUrl: extracted.dataUrl, file });
    const text = ocr.text;
    if (!text.trim()) {
      setError("OCR leer — kein erfundener Text. Cloud-OCR bleibt gesperrt.");
      return;
    }
    if (mode === "A" && !targetId && !speakerAs.startsWith("char:")) {
      setError("Mode A ohne Ziel prägt nichts.");
      return;
    }
    const charId = targetId || (speakerAs.startsWith("char:") ? speakerAs.slice(5) : "");
    const upload = {
      id: uid("up"),
      name: file.name || extracted.title,
      mime: file.type,
      text: text.slice(0, 20000),
      mode,
      targetKind: mode === "A" ? (charId ? "character" as const : "world" as const) : "session" as const,
      targetId: mode === "A" ? charId || w.id : s.id,
      worldId: w.id,
      sessionId: s.id,
      characterId: charId || undefined,
      note: "",
      committed: false,
      status: "ready" as const,
      createdAt: new Date().toISOString(),
      userId: activeUserId,
    };
    const ok = await addUpload(upload);
    if (!ok) {
      setError("Upload nicht gespeichert.");
      return;
    }
    const bound = await commitUpload(upload.id);
    if (!bound) {
      setError("Upload gespeichert, aber Wissen nicht gebunden. Siehe Logs.");
      return;
    }
    saveSession({ ...s, focus: { ...s.focus, uploadId: upload.id } });
    log({ level: "info", code: "UPLOAD", message: `${mode} ${file.name}`, sessionId: s.id });
    if (mode === "A") {
      setError("Mode A liegt im Review. Nichts wird ohne Freigabe geprägt.");
    }
    setUploadOpen(false);
  }

  const lastEffects = session.facts.slice(-8).reverse();
  const rt = targetChar ? session.runtimes[targetChar.id] : present[0] ? session.runtimes[present[0].id] : undefined;

  const visibleTurns = session.turns.filter((t, i) => {
    const speech = (t.speech || "").trim();
    if (!speech && !t.action) return false;
    if (t.role === "narrator") {
      const notes = (session.scene.notes || "").trim();
      if (i > 0 && notes && (speech === notes || speech.startsWith(notes.slice(0, 48)) || notes.startsWith(speech.slice(0, 48)))) return false;
    }
    // V35: Kein versteckter Anzeigefilter (§66). Früher wurden Reden mit zwei "..."-Stellen
    // ("Ich... weiß nicht... was ich sagen soll") ausgeblendet — kanonische Turns wurden unsichtbar.
    return true;
  });

  return (
    <Shell title={`Chat · ${session.name}`} flush>
      <div className="flex min-h-[calc(100dvh-6.75rem)] flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-elevated px-3 py-2.5 sm:px-4">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-[0.16em] text-faint">{world.name}</p>
          <h1 className="truncate font-display text-lg font-semibold leading-tight">{session.scene.placeName}</h1>
        </div>
        <div className="flex max-w-full flex-wrap gap-1">
          {present.map((c) => (
            <Chip key={c.id} hot={c.id === session.avatarId || c.id === targetId}>
              {c.name.split(" ")[0]}
            </Chip>
          ))}
        </div>
        <Button variant={regieOpen ? "primary" : "line"} className="min-h-11 shrink-0 text-sm" aria-expanded={regieOpen} onClick={() => setRegieOpen((v) => !v)}>
          {regieOpen ? "Steuerung ausblenden" : "Steuerung einblenden (Rollen, Puppet, Regie, Gott, Fate)"}
        </Button>
      </div>

      {regieOpen ? (
      <div className="border-b border-border px-3 py-3 sm:px-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-display text-xl font-semibold">MCC Chat</h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <Chip hot>Aktiv</Chip>
          <span>Turn {session.turnIndex}</span>
          <span>{world.name}</span>
          <span>{user?.name}</span>
          <Chip>{ROLES.find((r) => r.id === mode)?.label}</Chip>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-end gap-3 rounded-[16px] border border-border bg-elevated p-3">
        <div className="flex flex-wrap gap-1">
          {ROLES.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setRole(r.id)}
              className={cn(
                "min-h-10 rounded-[10px] px-3 text-sm",
                mode === r.id ? "bg-accent text-accent-fg" : "bg-subtle text-muted",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
        <label className="text-xs text-muted">
          Spreche als
          <Select value={speakerAs} onChange={(e) => setSpeakerAs(e.target.value)} className="mt-1 min-h-10" data-v92="spreche-als">
            <option value="" disabled>– bitte wählen –</option>
            <option value="avatar">Als Avatar</option>
            <option value="operator">Als Bedienperson (außerhalb der Welt)</option>
            <option value="observer">Als Beobachter</option>
            <option value="regie">Regie-Stimme</option>
            <option value="gott">Gott / System</option>
            {natives.map((c) => (
              <option key={c.id} value={`char:${c.id}`}>
                Puppet: {c.name}{session.scene.presentIds.includes(c.id) ? "" : " (nicht anwesend – wird beim Senden in die Szene geholt)"}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-muted">
          {godScope === "action" && (mode === "god" || speakerAs === "gott") ? "Handelnde Figur (God-Handlung)" : "Direktes Ziel (betroffene Figur, nicht der Handelnde)"}
          <Select value={targetId} onChange={(e) => setTargetId(e.target.value)} className="mt-1 min-h-10">
            <option value="">Ziel wählen…</option>
            {present.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </label>
        {mode === "regie" || speakerAs === "regie" ? (
          <label className="text-xs text-muted">
            Angewiesene Figur (wer handelt; bei Befehlen ohne Namen auswählen)
            <Select value={regieActorId} onChange={(e) => setRegieActorId(e.target.value)} className="mt-1 min-h-10">
              <option value="">Figur wählen…</option>
              {present.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        {mode === "regie" || speakerAs === "regie" ? (
          <label className="text-xs text-muted flex items-center gap-2" htmlFor="matrix-regie-direct">
            <input id="matrix-regie-direct" type="checkbox" className="h-5 w-5" />
            Handlung der gewählten Figur direkt als Szenenereignis vollziehen (ohne Modellinterpretation; keine zusätzlichen Körperfolgen erfinden)
          </label>
        ) : null}
        {mode === "god" || speakerAs === "gott" ? (
          <label className="text-xs text-muted">
            God-Scope
            <Select value={godScope} onChange={(e) => setGodScope(e.target.value as GodScope)} className="mt-1 min-h-10">
              {[["auto", "Automatisch (strukturiert: Körper, Wissen, Beziehung, Szene …)"], ["world", "world"], ["session", "session"], ["scene", "scene"], ["character", "character"], ["relationship", "relationship"], ["knowledge", "knowledge"], ["body", "body"], ["time", "time"], ["action", "action (konkrete Handlung)"]].map(([s, label]) => (
                <option key={s} value={s}>
                  {label}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        {mode === "regie" || speakerAs === "regie" || mode === "god" || speakerAs === "gott" ? (
          <label className="text-xs text-muted">
            Szenenübergang
            <Select
              aria-label="Szenenübergang dieser Anweisung"
              value={szenenUebergang}
              onChange={(e) => setSzenenUebergang(e.target.value as "neue_szene" | "szene_endet" | "keiner")}
              className="mt-1 min-h-10"
            >
              <option value="keiner">Kein Übergang (Szene läuft weiter)</option>
              <option value="neue_szene">Neue Szene beginnt mit dieser Anweisung</option>
              <option value="szene_endet">Szene endet mit dieser Anweisung</option>
            </Select>
          </label>
        ) : null}
        <Switch checked={session.pipeline.fate} onChange={(v) => patchPipeline("fate", v)} label="Fate" />
        <Switch checked={session.pipeline.meta} onChange={(v) => patchPipeline("meta", v)} label="Meta" />
        <Switch checked={session.pipeline.narrator} onChange={(v) => patchPipeline("narrator", v)} label="Erzähler" />
      </div>

      <div className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Info title="Systemlage">
          <Row k="Modus" v={mode} />
          <Row k="Sprecher" v={speakerAs} />
          <Row k="Avatar" v={avatar?.name ?? "keiner"} />
          <Row k="Uploadbezug" v={uploads.find((u) => u.id === session.focus.uploadId)?.name || session.focus.uploadId || "keiner"} />
          <Row k="Szene" v={`${session.scene.placeName} · ${session.scene.phase}`} />
        </Info>
        <Info title="AutoChat">
          <Row k="Status" v={session.autoChat.enabled ? `an · ${session.autoChat.turns} Turns · Pause ${Math.round(session.autoChat.delayMs / 1000)} s` : "aus — Schalter unter dem Eingabefeld (Steuerung) oder „Figuren jetzt weiterreden lassen“"} />
        </Info>
        <Info title="Sprecherwahl (Turn-Taking)">
          {speakerPick.length ? (
            speakerPick.slice(0, 4).map((c) => <Row key={c.id} k={`${c.name || c.id} · ${Number(c.score).toFixed(2)}`} v={(c.reasons || []).join(", ") || "—"} />)
          ) : (
            <p className="text-xs text-muted">Nach dem nächsten Turn: wer sprechen wollte und warum (Anrede, Frage, Druck, Kontext, Beziehung, Agenda, Fluss).</p>
          )}
        </Info>
        <Info title="Vereinbart / gilt (konjunktives Gedächtnis)">
          {(session.frames || []).length ? (
            (session.frames || []).slice(-8).reverse().map((f) => {
              const nm = (id?: string) => (id ? worldChars.find((c) => c.id === id)?.name || (id === session.avatarId ? session.alias || "Avatar" : id) : "");
              const st: Record<string, string> = { proposed: "vorgeschlagen", requested: "erbeten", accepted: "vereinbart", committed: "versprochen", refused: "abgelehnt", revoked: "abgesagt", fulfilled: "erfüllt", current: "gilt", superseded: "überholt" };
              return <Row key={f.id} k={`${f.kind}${f.when?.label ? " · " + f.when.label : ""}`} v={`${f.what.slice(0, 90)} — ${st[f.status] || f.status} (${nm(f.who)}${f.whom && f.whom !== f.who ? " → " + nm(f.whom) : ""}, Turn ${f.history?.[0]?.turn ?? "?"})`} />;
            })
          ) : (
            <p className="text-xs text-muted">Noch keine Vereinbarung, kein Versprechen, keine dauerhafte Offenbarung in dieser Session.</p>
          )}
        </Info>
        <Info title="Szene">
          {session.sceneState ? (() => {
            const st = session.sceneState!;
            const nm = (id?: string) => (id ? worldChars.find((c) => c.id === id)?.name || (id === session.avatarId ? session.alias || "Avatar" : id) : "—");
            const openBeats = (st.openBeats || []).filter((b) => b.status === "open");
            return (
              <>
                <Row k="Szenenstatus" v={`${st.status || "open"} · Eskalation ${Number(st.escalation || 0).toFixed(2)}`} />
                {st.nextBeatOwner ? <Row k="Nächster Beat" v={nm(st.nextBeatOwner)} /> : null}
                {st.lastPhysicalBeat?.text ? <Row k="Letzter phys. Beat" v={`${nm(st.lastPhysicalBeat.by)}: ${st.lastPhysicalBeat.text.slice(0, 60)} (T${st.lastPhysicalBeat.turn})`} /> : null}
                {st.lastEmotionalBeat?.emotion ? <Row k="Letzter emot. Beat" v={`${nm(st.lastEmotionalBeat.by)}: ${st.lastEmotionalBeat.emotion} ${st.lastEmotionalBeat.intensity ?? ""} (T${st.lastEmotionalBeat.turn})`} /> : null}
                {openBeats.length ? <Row k="Offene Beats" v={openBeats.map((b) => `${b.kind} → ${nm(b.owner)}: ${b.text.slice(0, 40)}`).join(" · ")} /> : null}
              </>
            );
          })() : null}
          <Row k="Ort" v={`${session.scene.placeName} · ${session.scene.time}`} />
          <Row k="Gefahr" v={session.scene.danger.toFixed(2)} />
          <Row
            k="Hört"
            v={
              session.scene.hearsIds === undefined
                ? "abgeleitet"
                : session.scene.hearsIds.length
                  ? session.scene.hearsIds.map((id) => worldChars.find((c) => c.id === id)?.name || id).join(", ")
                  : "niemand"
            }
          />
          <Row
            k="Sieht"
            v={
              session.scene.seesIds === undefined
                ? "abgeleitet"
                : session.scene.seesIds.length
                  ? session.scene.seesIds.map((id) => worldChars.find((c) => c.id === id)?.name || id).join(", ")
                  : "niemand"
            }
          />
          <Row k="Fragen" v={(session.scene.openQuestions || []).slice(0, 2).join(" · ") || "—"} />
          <Row k="Forderungen" v={(session.scene.openDemands || []).slice(0, 2).join(" · ") || "—"} />
          <Row k="Zusagen" v={(session.scene.openPromises || []).slice(0, 2).join(" · ") || "—"} />
          <Row k="Gegenstände" v={(session.scene.items || []).slice(0, 3).join(", ") || "—"} />
          {(session.scene.aftereffects || []).length ? (
            <p className="mt-1 text-[11px] text-muted">Nachwirkung: {(session.scene.aftereffects || []).slice(-1)[0]}</p>
          ) : null}
        </Info>
        <Info title="Pipeline">
          <p className="flex flex-wrap gap-1">
            <Chip tone={session.pipeline.fate ? "ok" : undefined}>Fate {session.pipeline.fate ? "an" : "aus"}</Chip>
            <Chip tone={session.pipeline.narrator ? "ok" : undefined}>Erzähler</Chip>
          </p>
          <p className="mt-2 text-[11px] text-faint">Fate spricht nie als Figur.</p>
        </Info>
        <Info title="Runtime-Vorschau">
          {rt ? (
            <>
              <Row k="Status" v={rt.emotion} />
              <Row k="Schmerz" v={rt.pain.toFixed(2)} />
              <Row k="Mobilität" v={rt.mobility.toFixed(2)} />
              <Row k="Sprechen" v={rt.canSpeak && !rt.gagged ? "ja" : "nein"} />
              {!rt.canSpeak || rt.gagged ? (
                <p className="mt-1 text-xs text-danger">Capability: Sprechen blockiert</p>
              ) : null}
              {rt.restrained || rt.mobility < 0.25 ? (
                <p className="mt-1 text-xs text-danger">Capability: Bewegung eingeschränkt</p>
              ) : null}
            </>
          ) : (
            <p className="text-xs text-faint">Ziel wählen</p>
          )}
        </Info>
        <Info title="Letzte Wirkungen">
          <ul className="max-h-24 space-y-1 overflow-auto text-[11px] text-muted">
            {lastEffects.slice(0, 5).map((f) => (
              <li key={f.id}>
                {f.kind}: {f.text.slice(0, 72)}
              </li>
            ))}
          </ul>
        </Info>
      </div>
      </div>
      ) : null}

      <div className={cn(regieOpen ? "grid min-h-0 flex-1 gap-3 overflow-hidden px-3 py-3 lg:grid-cols-[220px_minmax(0,1fr)_240px]" : "flex min-h-0 flex-1 flex-col")}>
        <aside className={cn("space-y-3 overflow-y-auto", !regieOpen && "hidden")}>
          <section className="rounded-[16px] border border-border bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">Szene</p>
            <h2 className="mt-1 font-display text-lg">{session.scene.placeName}</h2>
            <p className="text-xs text-muted">{session.scene.time}</p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-subtle">
              <div className="h-full bg-accent" style={{ width: `${Math.round(session.scene.tension * 100)}%` }} />
            </div>
            <p className="mt-3 text-[11px] uppercase tracking-wide text-muted">Anwesend — klicken schaltet</p>
            <ul className="mt-1 space-y-1">
              {natives.map((c) => {
                const on = session.scene.presentIds.includes(c.id);
                const pending = presencePending.includes(c.id);
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      aria-pressed={on}
                      aria-busy={pending}
                      disabled={pending}
                      className={cn("w-full min-h-11 rounded-[8px] px-2 py-1.5 text-left text-sm", on ? "bg-subtle text-fg" : "text-faint", pending && "opacity-70")}
                      onClick={() => togglePresence(c.id)}
                    >
                      {c.name}{pending ? " · schaltet…" : ""}
                      {!c.isWorldNative ? <Chip>Avatar</Chip> : null}
                    </button>
                  </li>
                );
              })}
            </ul>
            <button
              type="button"
              aria-expanded={perceptionOpen}
              className="mt-3 w-full min-h-11 rounded-[8px] border border-border px-2 py-1.5 text-left text-sm text-muted"
              onClick={() => setPerceptionOpen((open: boolean) => !open)}
            >
              Hören / Sehen — Sonderfälle {perceptionOpen ? "schließen" : "öffnen"}
            </button>
            <p className="mt-1 text-[11px] text-faint">
              Normalfall: Anwesenheit und tatsächliche Wahrnehmungsfähigkeit entscheiden. Manuelle Ausnahmen bleiben erhalten.
            </p>
            {(["hearsIds", "seesIds"] as const).map((kind) =>
              Array.isArray(session.scene[kind]) ? (
                <p key={`scope-${kind}`} className="mt-1 text-[11px] text-muted">
                  {kind === "hearsIds" ? "Hört" : "Sieht"} manuell: {session.scene[kind]?.length
                    ? session.scene[kind]!.map((id) => natives.find((c) => c.id === id)?.name || id).join(", ")
                    : "Niemand"}
                </p>
              ) : null,
            )}
            {perceptionOpen ? (["hearsIds", "seesIds"] as const).map((kind) => {
              const label = kind === "hearsIds" ? "Hört" : "Sieht";
              const emptyName = kind === "hearsIds" ? "Niemand hört" : "Niemand sieht";
              const cur = session.scene[kind];
              const explicitEmpty = Array.isArray(cur) && cur.length === 0;
              return (
                <div key={kind}>
                  <p className="mt-3 text-[11px] uppercase tracking-wide text-muted">{label} — klicken schaltet</p>
                  <button
                    type="button"
                    aria-label={emptyName}
                    className={cn("mt-1 w-full min-h-11 rounded-[8px] px-2 py-1.5 text-left text-sm", explicitEmpty ? "bg-subtle text-fg" : "text-faint")}
                    onClick={() => patchPerception(kind, [])}
                  >
                    {emptyName}
                  </button>
                  <button
                    type="button"
                    aria-label={`${label} automatisch aus Anwesenheit`}
                    className={cn("mt-1 w-full min-h-11 rounded-[8px] px-2 py-1.5 text-left text-sm", cur === undefined ? "bg-subtle text-fg" : "text-faint")}
                    onClick={() => patchPerception(kind, [], false)}
                  >
                    Automatisch aus Anwesenheit
                  </button>
                  <ul className="mt-1 space-y-1">
                    {natives.map((c) => {
                      const on = (cur ?? session.scene.presentIds).includes(c.id);
                      return (
                        <li key={`${kind}-${c.id}`}>
                          <button
                            type="button"
                            aria-label={`${label} ${c.name}`}
                            className={cn("w-full min-h-11 rounded-[8px] px-2 py-1.5 text-left text-sm", on && !explicitEmpty ? "bg-subtle text-fg" : "text-faint")}
                            onClick={() => togglePerception(kind, c.id)}
                          >
                            {c.name}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            }) : null}
            <p className="mt-3 text-[11px] uppercase tracking-wide text-muted">Orte</p>
            <ul className="mt-1 space-y-1">
              {world.places.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={cn("w-full rounded-[8px] px-2 py-1.5 text-left text-sm", p.id === session.scene.placeId ? "text-accent" : "text-muted")}
                    onClick={() => {
                      const moverId = session.avatarId || targetId || "";
                      if (!moverId) {
                        setError("Ortswechsel braucht Avatar oder gewähltes Ziel.");
                        return;
                      }
                      void kernelMove({
                        session,
                        world,
                        placeId: p.id,
                        moverId,
                      })
                        .then(({ session: next, trace }) => applyKernel(next, trace))
                        .catch((e) => setError(e instanceof Error ? e.message : "Ortswechsel fehlgeschlagen"));
                    }}
                  >
                    {p.name}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>

        <section className="flex min-h-0 flex-1 flex-col bg-bg">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <p className="text-sm font-medium">Gespräch</p>
            <Switch checked={debug} onChange={setDebug} label="Debug" />
          </div>
          <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-4" role="log">
            {session.turns.length === 0 ? (
              <article className="mx-auto max-w-2xl rounded-[16px] bg-elevated px-4 py-3 text-center text-sm text-muted">
                <p className="text-[11px] uppercase tracking-wide text-faint">Szene</p>
                <p className="mt-0.5 whitespace-pre-wrap">{session.scene.notes || session.scene.openMatters?.[0] || "Die Szene steht. Noch keine Rede."}</p>
              </article>
            ) : null}
            {visibleTurns.map((t) => {
              const mine = t.role === "avatar" || t.role === "teilnehmer" || t.role === "observer";
              const meta = t.role === "god" || t.role === "regie" || t.role === "narrator" || t.role === "fate";
              return (
              <article
                key={t.id}
                className={cn(
                  "max-w-[min(40rem,92%)] rounded-[16px] px-4 py-2.5 text-[15px] leading-relaxed",
                  mine ? "ml-auto bg-subtle" : meta ? "mx-auto bg-transparent text-center text-muted" : "bg-elevated",
                )}
              >
                <p className="text-[11px] uppercase tracking-wide text-faint">
                  {t.speakerName}
                  {debug && t.firedSpaces.length ? ` · ${t.firedSpaces.join(", ")}` : ""}
                  {debug && t.source === "synapse" ? " · Synapse" : ""}
                </p>
                <p className="mt-0.5 whitespace-pre-wrap">{t.speech}</p>
                {t.action ? <p className="mt-1 text-xs italic text-muted">{t.action}</p> : null}
                {/* V65T (AMASTER §71.2.1/G12): canonical outcome of this row's commit (Einwilligung, Regie-Wirkung, Figurenreaktion) */}
                {(t as { ausgang?: string }).ausgang ? (
                  <p className="mt-1 text-[11px] text-faint" data-v65t="ausgang">{(t as { ausgang?: string }).ausgang}</p>
                ) : null}
                {t.role === "character" && ((t.synapses && t.synapses.length) || typeof t.recallCount === "number") ? (
                  <p className="mt-1 text-[11px] text-faint">
                    {t.synapses && t.synapses.length
                      ? `Synapsen: ${t.synapses.map((x) => `${x.space} ${Number(x.activation || 0).toFixed(2)}${x.source && x.source !== "lexikalisch" ? "·" + x.source : ""}`).join(", ")}`
                      : "Synapsen: keine"}
                    {t.synapseEffect?.runtimeDelta?.emotion ? ` → ${String(t.synapseEffect.runtimeDelta.emotion.to)}` : ""}
                    {t.synapseEffect?.relationDelta?.length ? ` · Beziehung zu ${t.synapseEffect.relationDelta.map((r) => r.toName).join(", ")} bewegt` : ""}
                    {typeof t.recallCount === "number" ? ` · Erinnerungen im Spiegel: ${t.recallCount}` : ""}
                  </p>
                ) : null}
                {t.role === "character" && (t as { contradiction?: { items?: Array<{ aussage?: string; bekannt?: string; art?: string }> } }).contradiction?.items?.length ? (
                  <p className="mt-1 text-[11px] text-danger">
                    Widerspruch bemerkt: {(t as { contradiction: { items: Array<{ aussage?: string; bekannt?: string; art?: string }> } }).contradiction.items.map((i) => `„${i.aussage}“ vs. „${i.bekannt}“${i.art === "selbstwiderspruch" ? " (Selbstwiderspruch)" : ""}`).join(" · ")} — Vertrauen sinkt
                  </p>
                ) : null}
              </article>
              );
            })}
            {pendingSpeech ? (
              <article className="ml-auto max-w-[92%] rounded-[12px] bg-subtle px-3 py-2 text-sm opacity-70">
                <p className="text-[11px] uppercase tracking-wide text-faint">Du · wird geschrieben</p>
                <p className="mt-0.5 whitespace-pre-wrap">{pendingSpeech}</p>
              </article>
            ) : null}
            {debug && fires.length ? (
              <pre className="rounded-[8px] bg-bg p-2 font-mono text-[11px] text-muted">
                {JSON.stringify(
                  {
                    synapsen: fires.map((f) => ({ r: f.space, a: f.activation.toFixed(2) })),
                    facts: session.facts.slice(-6).map((f) => ({ k: f.kind, t: f.text.slice(0, 80), w: f.witnessedBy.length })),
                  },
                  null,
                  2,
                )}
              </pre>
            ) : null}
          </div>
          <div className="border-t border-border bg-elevated p-3 sm:p-4">
            {llmNotice ? (
              <p className="mb-2 rounded-[10px] border border-danger/40 bg-danger/10 p-2 text-sm text-danger" role="alert">
                {llmNotice}
              </p>
            ) : null}
            {mode === "beobachter" ? <p className="mb-2 text-xs text-muted">Beobachter: Kommentar oder Beschreibung, ohne Figurenrede. Figuren handeln nicht automatisch.</p> : null}
            {triggerHints.length ? (
              <div className="mb-2 flex flex-wrap items-center gap-1">
                <span className="text-[11px] uppercase tracking-wide text-muted">Analysehinweis · nicht-kanon</span>
                {triggerHints.map((h, i) => (
                  <Chip key={`${h}-${i}`} tone="warn">
                    {h}
                  </Chip>
                ))}
              </div>
            ) : null}
            {!speakerAs ? (
              <p className="mb-2 text-sm text-warn" role="status" data-v92="sprecher-waehlen">
                Sprecherbindung fehlt – bitte unter „Spreche als“ wählen, wie du sprichst. Bis dahin wird nichts gespeichert.
              </p>
            ) : null}
            <Textarea
              rows={3}
              value={text}
              disabled={writeLocked}
              aria-label="Chat-Eingabe"
              placeholder={mode === "beobachter" ? "Beobachterkommentar — beschreibt oder steuert, spricht nicht als Figur." : "Sag etwas in der Szene…"}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <Button onClick={() => void send()} disabled={writeLocked}>
                Senden
              </Button>
              <Button
                variant="line"
                onClick={mic}
                disabled={writeLocked}
                aria-pressed={recording}
                aria-label={recording ? "Aufnahme abbrechen" : `Aufnahme ${user?.sttMode === "autosend" ? "· Auto-Senden" : "· Diktat"}`}
              >
                {recording ? "Aufnahme läuft · Abbrechen" : `Aufnahme ${user?.sttMode === "autosend" ? "· Auto-Senden" : "· Diktat"}`}
              </Button>
              {regieOpen ? (
                <>
              <Button
                variant="line"
                onClick={() => {
                  if (user) patchUser(user.id, { sttMode: user.sttMode === "autosend" ? "dictation" : "autosend" });
                }}
              >
                STT-Modus
              </Button>
              <Button variant="line" onClick={() => setUploadOpen(true)}>
                Upload
              </Button>
              <Button variant="danger" onClick={stop}>
                Stoppen
              </Button>
                </>
              ) : null}
            </div>
            {hint ? (
              <p className="mt-2 text-sm text-warn" role="status" aria-live="polite" data-v92="eingabe-hinweis">{hint}</p>
            ) : null}
            {error ? (
              <div>
                <p className="mt-2 text-sm text-danger" role="alert" aria-live="assertive">{error}</p>
              </div>
            ) : null}
            {klaerung ? (
              <div className="mt-2 rounded border border-line p-2 text-sm" role="group" aria-label="Rückfrage zur Person" data-v92="identitaet-klaeren">
                {klaerung.fragen.map((f, i) => {
                  const a = klaerung.antworten.find((x) => x.frage === f.frage);
                  return (
                    <div key={f.frage} className="mt-1" data-v92-stelle={i + 1}>
                      <p>
                        Wer ist mit „{f.text}“ gemeint?{klaerung.fragen.length > 1 ? ` (Stelle ${i + 1} von ${klaerung.fragen.length})` : ""} Bis zur Antwort wird nichts gespeichert.
                      </p>
                      {f.vor !== undefined || f.nach !== undefined ? (
                        <p className="text-xs text-muted" data-v92-kontext>
                          „…{f.vor}<strong>{f.text}</strong>{f.nach}…“
                        </p>
                      ) : null}
                      <div className="mt-1 flex flex-wrap gap-2">
                        {f.kandidaten.map((c) => (
                          <Button key={c.id} variant="line" data-v92-klaerung={c.id} disabled={busy || writeLocked} onClick={() => klaere(f.frage, c.id)}>
                            {klaerungLabel(f, c)}{a?.id === c.id ? " ✓" : ""}
                          </Button>
                        ))}
                        <Button variant="line" data-v92-klaerung="niemand" disabled={busy || writeLocked} onClick={() => klaere(f.frage, null)}>
                          Niemand davon{a && a.id === null ? " ✓" : ""}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
            {pendingView && !busy ? (
              <div className="mt-2 rounded border border-line p-2 text-sm" role="status" data-v65u="offene-eingabe">
                <p>
                  Die Eingabe „{pendingView.text}“ (Turn {String(pendingView.turn ?? "?")}) wartet auf ihre Antwort — Antwortversuch:{" "}
                  {pendingView.attemptUnklar
                    ? "nicht nachweisbar beendet (läuft womöglich in einem anderen Serverprozess; Abschließen gesperrt)"
                    : pendingView.attemptRunning ? "läuft" : ATTEMPT_DE[String(pendingView.attempt?.state ?? "")] ?? "nicht erfasst"}
                  {pendingView.attempt?.error ? ` (${String(pendingView.attempt.error).slice(0, 80)})` : ""}.
                  {pendingView.attemptUnklar ? " Ein ausdrücklicher neuer Antwortversuch ist möglich; unter Umständen läuft noch ein alter Versuch. Nur die zuerst gespeicherte Antwort zählt. Abschließen bleibt gesperrt." : ""}
                </p>
                <div className="mt-1 flex flex-wrap gap-2">
                  <Button variant="line" data-v65u="antwort-erneut" disabled={!canExplicitlyRetryPendingAttempt(pendingView) || writeLocked}
                    onClick={() => void resumePending(pendingView)}>
                    Antwort erneut erzeugen
                  </Button>
                  <Button variant="line" data-v65u="eingabe-abschliessen" disabled={pendingView.attemptRunning || writeLocked}
                    onClick={() => void closePending(pendingView)}>
                    Eingabe ohne Antwort abschließen
                  </Button>
                  <Button variant="line" data-v65u="status-pruefen" disabled={busy}
                    onClick={() => void refreshPending()}>
                    Status neu prüfen
                  </Button>
                </div>
              </div>
            ) : null}
            {busy ? <p className="mt-2 text-xs text-accent" aria-live="polite">Turn läuft…</p> : null}
            {regieOpen ? (
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              <Switch
                checked={session.autoChat.enabled}
                onChange={(v) => {
                  if (!v) cancelAutoChain();
                  // V47: sofort im Store (Schalter reagiert ohne Round-Trip), dann kanonisch speichern
                  useMatrix.setState({ sessions: useMatrix.getState().sessions.map((x) => (x.id === session.id ? { ...x, autoChat: { ...x.autoChat, enabled: v } } : x)) });
                  saveSession({ ...session, autoChat: { ...session.autoChat, enabled: v } });
                  log({ level: "info", code: v ? "AUTOCHAT_ON" : "AUTOCHAT_OFF", message: `turns=${session.autoChat.turns} delayMs=${session.autoChat.delayMs}`, sessionId: session.id });
                }}
                label="AutoChat"
              />
              <Button
                variant="line"
                className="min-h-11"
                disabled={busy}
                onClick={() => {
                  log({ level: "info", code: "AUTOCHAT_MANUAL", message: `turns=${session.autoChat.turns}`, sessionId: session.id });
                  queueAuto(Math.max(1, session.autoChat.turns), 0);
                }}
              >
                Figuren jetzt weiterreden lassen ({Math.max(1, session.autoChat.turns)})
              </Button>
              <label className="text-muted">
                Turns
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={session.autoChat.turns}
                  className="ml-1 w-12 rounded-[8px] border border-border bg-bg px-1 py-1"
                  onChange={(e) => saveSession({ ...session, autoChat: { ...session.autoChat, turns: Number(e.target.value) } })}
                />
              </label>
              <label className="text-muted">
                Pause s
                <input
                  type="number"
                  min={3}
                  max={10}
                  value={Math.round(session.autoChat.delayMs / 1000)}
                  className="ml-1 w-12 rounded-[8px] border border-border bg-bg px-1 py-1"
                  onChange={(e) => saveSession({ ...session, autoChat: { ...session.autoChat, delayMs: Number(e.target.value) * 1000 } })}
                />
              </label>
            </div>
            ) : null}
          </div>
        </section>

        <aside className={cn("space-y-3 overflow-y-auto", !regieOpen && "hidden")}>
          <section className="rounded-[16px] border border-border bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">Avatar</p>
            <p className="mt-1 text-[11px] text-muted">Eigene Avatare, freigegebene Stämme, oder hier neu anlegen.</p>
            <Select
              className="mt-2"
              value={session.avatarId ?? ""}
              onChange={(e) => {
                const id = e.target.value || null;
                const fig = id ? worldChars.find((c) => c.id === id) : undefined;
                // V63 (AMASTER §24.1): the chosen figure keeps its identity; the
                // alias follows its name, as on the other two avatar paths
                // ("Anlegen", character page). Before, the start default
                // "Spieler" stayed while the avatar was a named world figure.
                saveSession({ ...session, avatarId: id, ...(fig ? { alias: fig.name } : {}) });
                if (id && fig && fig.isWorldNative && !fig.canBeAvatar) patchCharacter(id, { canBeAvatar: true });
              }}
            >
              <option value="">Kein Avatar / externer User</option>
              {worldChars
                .filter((c) => c.isWorldNative === false || Boolean(c.canBeAvatar))
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.isWorldNative ? "" : " (Avatar)"}
                  </option>
                ))}
              {worldChars
                .filter((c) => c.isWorldNative && !c.canBeAvatar)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    Stamm als Avatar: {c.name}
                  </option>
                ))}
            </Select>
            <div className="mt-2 flex gap-2">
              <Input
                value={newAvatarName}
                onChange={(e) => setNewAvatarName(e.target.value)}
                placeholder="Neuen Avatar anlegen — Name"
              />
              <Button
                variant="ok"
                className="min-h-11 shrink-0 text-xs"
                onClick={() => {
                  const n = newAvatarName.trim();
                  if (!n) {
                    setAvatarErr("Name nötig.");
                    return;
                  }
                  const c = { ...makeOutsiderAvatar(n), id: uid("av"), worldId: session.worldId, canBeAvatar: true };
                  setAvatarErr(null);
                  void addCharacter(c).then((ok) => {
                    if (!ok) {
                      const fail = useMatrix.getState().logs.find((l) => l.code === "PERSIST_FAILED");
                      setAvatarErr(fail?.message || "Avatar konnte nicht gespeichert werden.");
                      return;
                    }
                    saveSession({ ...session, avatarId: c.id, alias: n });
                    setNewAvatarName("");
                  });
                }}
              >
                Anlegen
              </Button>
            </div>
            {avatarErr ? <p className="mt-1 text-xs text-danger">{avatarErr}</p> : null}
            <p className="mt-3 text-[11px] uppercase tracking-wide text-muted">Alias</p>
            <input
              className="mt-1 min-h-10 w-full rounded-[12px] border border-border bg-bg px-3 text-sm"
              value={session.alias}
              onChange={(e) => saveSession({ ...session, alias: e.target.value })}
            />
            <p className="mt-3 text-[11px] uppercase tracking-wide text-muted">Uploadbezug für den Turn</p>
            <Select
              className="mt-1"
              value={session.focus.uploadId ?? ""}
              onChange={(e) => saveSession({ ...session, focus: { ...session.focus, uploadId: e.target.value || undefined } })}
            >
              <option value="">Kein Upload</option>
              {uploads
                .filter((u) => u.sessionId === session.id || u.worldId === session.worldId)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} · {u.mode}
                  </option>
                ))}
            </Select>
          </section>
          <section className="rounded-[16px] border border-border bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">Snapshots</p>
            <div className="mt-2 flex flex-wrap gap-1">
              <Button variant="line" className="min-h-9 px-3 text-xs" onClick={() => addSnapshot(session.id)}>
                Erstellen
              </Button>
            </div>
            <ul className="mt-2 space-y-1">
              {snapshots
                .filter((s) => s.sessionId === session.id)
                .slice(0, 6)
                .map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate">{s.name}</span>
                    {s.erfasst?.durch === "server" ? (
                      <Button variant="ghost" className="min-h-8 px-2 text-xs" onClick={() => confirmReset("restore", s.name) && restoreSnapshot(s.id)}>
                        Wiederherstellen
                      </Button>
                    ) : (
                      // V66 (Audit6 N05): not this server's capture (imported or older) - kept as archive, not restorable
                      <span className="text-[11px] text-muted" title="nicht vom Server erfasst – nur Archiv">
                        nur Archiv
                      </span>
                    )}
                  </li>
                ))}
            </ul>
            {(() => {
              const mine = snapshots.filter((s) => s.sessionId === session.id);
              if (mine.length < 2) return <p className="mt-2 text-[11px] text-muted">Versionsvergleich braucht zwei Stände.</p>;
              const a = mine[0]?.session;
              const b = mine[1]?.session;
              return (
                <p className="mt-2 text-[11px] text-muted">
                  Versionsvergleich {mine[0]?.name} vs {mine[1]?.name}: Turns {(a?.turnIndex ?? 0) - (b?.turnIndex ?? 0)} · Memory{" "}
                  {(a?.memories?.length ?? 0) - (b?.memories?.length ?? 0)} · Facts {(a?.facts?.length ?? 0) - (b?.facts?.length ?? 0)}
                </p>
              );
            })()}
          </section>
          <section className="rounded-[16px] border border-border bg-elevated p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted">Offene Matters</p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted">
              {session.scene.openMatters.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] uppercase tracking-wide text-muted">Fate</p>
            <p className="text-xs text-muted">{session.fate.enabled ? session.fate.beat : "aus"}</p>
          </section>
        </aside>
      </div>
      </div>

      {uploadOpen ? (
        <div className="fixed inset-0 z-40 flex items-end justify-center bg-bg/70 p-4 sm:items-center" onClick={() => setUploadOpen(false)}>
          <div className="w-full max-w-md rounded-[16px] border border-border bg-elevated p-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-display text-lg">Upload im Chat</h3>
            <p className="mt-1 text-xs text-muted">Mode A prägt nur ein ausdrücklich gewähltes Ziel. Mode B bleibt Beobachtung in dieser Session. Gewählt: {uploadMode}.</p>
            <label className="mt-4 flex min-h-16 cursor-pointer flex-col items-center justify-center rounded-[12px] border border-dashed border-border px-3 py-3 text-sm text-muted">
              Datei wählen ({uploadMode})
              <input
                type="file"
                className="mt-2"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void onUploadFile(f, uploadMode);
                }}
              />
            </label>
            <Textarea
              className="mt-3"
              rows={3}
              placeholder="Oder Text einfügen"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  const t = (e.target as HTMLTextAreaElement).value.trim();
                  if (t) void onUploadFile(new File([t], "einfuegen.txt", { type: "text/plain" }), uploadMode);
                }
              }}
            />
            <Button
              className="mt-2 w-full"
              variant="line"
              onClick={(e) => {
                const box = (e.currentTarget.parentElement?.querySelector("textarea") as HTMLTextAreaElement | null)?.value.trim();
                if (!box) {
                  setError("Text einfügen oder Datei wählen.");
                  return;
                }
                void onUploadFile(new File([box], "einfuegen.txt", { type: "text/plain" }), uploadMode);
              }}
            >
              Text als Upload speichern
            </Button>
            <div className="mt-3 flex gap-2">
              <Button
                variant={uploadMode === "A" ? "primary" : "line"}
                onClick={() => setUploadMode("A")}
              >
                A · Prägung
              </Button>
              <Button variant={uploadMode === "B" ? "primary" : "line"} onClick={() => setUploadMode("B")}>
                B · Beobachtung
              </Button>
              <Button variant="ghost" onClick={() => setUploadOpen(false)}>
                Abbrechen
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </Shell>
  );
}

function Info({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[16px] border border-border bg-elevated p-3">
      <p className="mb-2 text-[11px] uppercase tracking-wide text-muted">{title}</p>
      {children}
    </section>
  );
}
function Row({ k, v }: { k: string; v: string }) {
  return (
    <p className="flex justify-between gap-2 text-xs">
      <span className="text-faint">{k}</span>
      <span className="truncate text-fg">{v}</span>
    </p>
  );
}

function speak(text: string) {
  try {
    if (typeof speechSynthesis !== "undefined" && speechSynthesis.speaking) {
      speechSynthesis.cancel();
    }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "de-DE";
    speechSynthesis.speak(u);
  } catch {
    /* ignore */
  }
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognition;
    webkitSpeechRecognition?: new () => SpeechRecognition;
  }
  interface SpeechRecognition extends EventTarget {
    lang: string;
    start: () => void;
    stop: () => void;
    onresult: ((ev: SpeechRecognitionEvent) => void) | null;
    onend: (() => void) | null;
  }
  interface SpeechRecognitionEvent {
    results: { [i: number]: { [j: number]: { transcript: string } } };
  }
}
