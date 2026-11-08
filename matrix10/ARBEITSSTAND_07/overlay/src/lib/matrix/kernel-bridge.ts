/** UI → Flask kernel → SQLite. Canonical commit path (B14 cutover). */
import type { KlaerungAntwort } from "./eingabe-hinweis";
import { apiGetSession, apiKernelCommit, apiKernelGod, apiKernelRegie, apiKernelPuppet, apiKernelPrepare, apiKernelMove, apiKernelPresence, apiKernelFate, apiKernelAutochatGate, apiKernelReset, apiKernelPerception, apiPostLiveLog } from "./api";
import { splitPuppet } from "./event-engine";
import { hydrateSession } from "./normalize";
import type { Session, StammCharacter, World } from "./types";

export function authorityForUiRole(role: string): string {
  if (role === "avatar") return "avatar";
  if (role === "teilnehmer") return "teilnehmer";
  if (role === "god") return "god";
  if (role === "regie") return "regie";
  if (role === "beobachter") return "observer";
  return "observer";
}

export function inputActorForSession(session: { role: string; avatarId: string | null }, speakAs?: string): string {
  const as = (speakAs || "").toLowerCase();
  if (as === "operator" || as === "user" || as === "bedienperson") return "user";
  if (as === "observer" || session.role === "beobachter") return "observer";
  if (as.startsWith("char:")) return as.slice(5);
  if (as === "avatar" || session.role === "avatar") return session.avatarId || "user";
  if (session.role === "teilnehmer") return session.avatarId || "user";
  return session.avatarId || "user";
}

export function mergeKernelSession(prev: Session, raw: Record<string, unknown>): Session {
  return hydrateSession({
    ...prev,
    ...(raw as unknown as Session),
    pipeline: (raw.pipeline as Session["pipeline"]) ?? prev.pipeline,
    autoChat: (raw.autoChat as Session["autoChat"]) ?? prev.autoChat,
    role: (raw.role as Session["role"]) ?? prev.role,
    name: (raw.name as string) ?? prev.name,
    alias: (raw.alias as string) ?? prev.alias,
  });
}

export type KernelTrace = {
  writePath: string;
  storeTurn: number;
  storeFacts: number;
  readTurn: number | null;
  readFacts: number | null;
  readOk: boolean;
  traceId: string;
};

function newTraceId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
}

// Diagnose darf den Produkt-Turn weder blockieren noch endlos Requests offen halten.
// Die Log-Antwort ist kein Bestandteil des kanonischen Commits.
async function liveTrace(stage: string, traceId: string, extra: Record<string, unknown> = {}): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);
  void apiPostLiveLog({ stage, trace_id: traceId, ...extra }, controller.signal)
    .catch(() => { /* Diagnose optional; niemals Produkt-Wahrheit */ })
    .finally(() => clearTimeout(timeout));
}

function factIds(session: Record<string, unknown> | undefined): string[] {
  const facts = (session?.facts as { id?: string }[] | undefined) ?? [];
  return facts.map((f) => String(f.id || "")).filter(Boolean).slice(0, 8);
}

function stammSpeakerPayload(c: StammCharacter): Record<string, unknown> {
  return {
    id: c.id,
    name: c.name,
    role: c.role,
    aliases: c.aliases,
    knowledge: c.knowledge,
    typicalPhrases: c.typicalPhrases,
    taboos: c.taboos,
    values: c.values,
    reactionRules: c.reactionRules,
    speechRegister: c.speechRegister,
    personality: c.personality,
    body: c.body,
    compass: c.compass,
    canon: c.canon,
    species: c.species,
    coreFacts: c.coreFacts,
    bindingPatterns: c.bindingPatterns,
    lastingAbilities: c.lastingAbilities,
    humor: c.humor,
    favoriteWords: c.favoriteWords,
    fears: c.fears,
    secrets: c.secrets,
    likes: c.likes,
    dislikes: c.dislikes,
    goals: c.goals,
    conflictStyle: c.conflictStyle,
    biography: c.biography,
    origin: c.origin,
    age: c.age,
    gender: c.gender,
    occupation: c.occupation,
    dialect: c.dialect,
    appearance: c.appearance,
    typicalPlace: c.typicalPlace,
  };
}

async function readBack(sessionId: string): Promise<{ ok: boolean; session?: Record<string, unknown> }> {
  try {
    const got = await apiGetSession(sessionId, { timeoutMs: 12000 });
    return { ok: Boolean(got?.ok && got.session), session: got.session };
  } catch {
    return { ok: false };
  }
}

function kernelTrace(writePath: string, stored: Record<string, unknown>, merged: Session, read: { ok: boolean; session?: Record<string, unknown> }, traceId: string): KernelTrace {
  const facts = (stored.facts as unknown[] | undefined) ?? [];
  const readFacts = (read.session?.facts as unknown[] | undefined) ?? [];
  return {
    writePath,
    storeTurn: Number(stored.turnIndex ?? merged.turnIndex),
    storeFacts: facts.length,
    readTurn: read.ok ? Number(read.session?.turnIndex ?? null) : null,
    readFacts: read.ok ? readFacts.length : null,
    readOk: read.ok,
    traceId,
  };
}

export async function kernelPrepare(opts: {
  session: Session;
  speaker: StammCharacter;
  /** V40: Sprecherwahl dem Server (Turn-Taking-Heuristik) überlassen; speaker ist dann nur Platzhalter */
  autoPick?: boolean;
  /** V46: verbindliche Regie-Anweisung, die die Figur in diesem Turn umsetzt */
  directive?: string;
  present: StammCharacter[];
  stimulus: string;
  userSpeech?: string;
  userName?: string;
  targetId?: string;
  speakAs?: string;
  inputKind?: string;
  /** V65U (Plan U4 "Antwort erneut erzeugen"): resume exactly this open input (stored TurnTruth), whatever the UI selection is */
  resumePendingId?: string;
  /** V92 Paket 16: the operator's answers to the server's identity clarification of THIS input */
  klaerungen?: KlaerungAntwort[];
}): Promise<{
  session: Session;
  truth: Record<string, unknown>;
  brainContext: Record<string, unknown> | undefined;
  traceId: string;
  /** Stand 07 / K-01: the server's proof of this prepared turn - formulate and commit accept the turn only with it */
  turnBeleg?: string;
  speakerCandidates?: Array<{ id: string; name?: string; score: number; reasons?: string[] }>;
}> {
  const authority = authorityForUiRole(opts.session.role);
  const traceId = newTraceId("kpr");
  const inputKind = opts.inputKind || (opts.userSpeech ? "speech" : "speech");
  const isAutochat = inputKind === "autochat";
  const inputActorId = inputActorForSession(opts.session, opts.speakAs);
  await liveTrace("TURN_START", traceId, {
    user_id: opts.session.userId,
    session_id: opts.session.id,
    authority,
  });
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/prepare" });
  const truth = {
    userId: opts.session.userId,
    operatorId: opts.session.userId,
    worldId: opts.session.worldId,
    sessionId: opts.session.id,
    role: opts.session.role,
    speakerId: opts.speaker.id,
    responseSpeakerId: opts.speaker.id,
    avatarId: opts.session.avatarId,
    inputActorId,
    speakAs: opts.speakAs || (opts.session.role === "beobachter" ? "observer" : opts.session.avatarId ? "avatar" : "operator"),
    targetId: opts.targetId ?? null,
    authority,
    presentIds: opts.session.scene.presentIds,
    inputKind: isAutochat ? "autochat" : inputKind,
    text: isAutochat ? "" : opts.userSpeech ?? opts.stimulus,
    ...(opts.directive ? { directive: opts.directive } : {}),
    userName: opts.userName,
    sceneId: opts.session.scene.placeId,
    timeRef: opts.session.scene.time,
    uploadRef: (opts.session.focus as { uploadId?: string }).uploadId,
    ...(opts.session.scene.hearsIds !== undefined ? { hearsIds: opts.session.scene.hearsIds } : {}),
    ...(opts.session.scene.seesIds !== undefined ? { seesIds: opts.session.scene.seesIds } : {}),
  };
  const prepared = await apiKernelPrepare({
    session: opts.session,
    actorUserId: opts.session.userId,
    trace_id: traceId,
    truth,
    speaker: stammSpeakerPayload(opts.speaker),
    present: opts.present.map((c) => ({ id: c.id, name: c.name, aliases: c.aliases })),
    ...(opts.autoPick ? { autoPick: true } : {}),
    ...(opts.resumePendingId ? { resumePending: { turnTruthId: opts.resumePendingId } } : {}),
    ...(opts.klaerungen?.length ? { klaerungen: opts.klaerungen } : {}),
  });
  const stored = (prepared.session || opts.session) as Record<string, unknown>;
  await liveTrace("READER", traceId, { reader: "PREPARE", record_ids: factIds(stored) });
  const merged = mergeKernelSession(opts.session, stored);
  return {
    session: merged,
    truth: (prepared.truth as Record<string, unknown> | undefined) || truth,
    brainContext: prepared.brainContext,
    speakerCandidates: (prepared.speakerCandidates as Array<{ id: string; name?: string; score: number; reasons?: string[] }> | undefined) || [],
    traceId,
    turnBeleg: typeof prepared.turnBeleg === "string" ? prepared.turnBeleg : undefined,
  };
}

export async function kernelCommitFigure(opts: {
  session: Session;
  speaker: StammCharacter;
  present: StammCharacter[];
  result: { speech: string; action: string | null; proposals?: Record<string, unknown> };
  fired: { space: string }[];
  recallCount?: number;
  contradictions?: unknown[];
  userSpeech?: string;
  userName?: string;
  truth?: Record<string, unknown>;
  traceId?: string;
  /** Stand 07 / K-01: proofs of the prepared turn and of the server's formulation (the commit takes no client text) */
  turnBeleg?: string;
  formulierungsBeleg?: string;
}): Promise<{ session: Session; trace: KernelTrace }> {
  const authority = authorityForUiRole(opts.session.role);
  const traceId = opts.traceId || newTraceId("kc");
  if (!opts.traceId) {
    await liveTrace("TURN_START", traceId, {
      user_id: opts.session.userId,
      session_id: opts.session.id,
      authority,
    });
  }
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/commit" });
  const truth = opts.truth ?? {
    userId: opts.session.userId,
    operatorId: opts.session.userId,
    worldId: opts.session.worldId,
    sessionId: opts.session.id,
    role: opts.session.role,
    speakerId: opts.speaker.id,
    responseSpeakerId: opts.speaker.id,
    avatarId: opts.session.avatarId,
    inputActorId: inputActorForSession(opts.session),
    targetId: null, // Server binds the real addressee from the current event, never a retained UI focus.
    authority,
    presentIds: opts.session.scene.presentIds,
    inputKind: "speech",
    text: opts.userSpeech ?? opts.result.speech,
    uploadRef: (opts.session.focus as { uploadId?: string }).uploadId,
  };
  const written = await apiKernelCommit({
    session: opts.session,
    actorUserId: opts.session.userId,
    trace_id: traceId,
    truth,
    speaker: { id: opts.speaker.id, name: opts.speaker.name },
    present: opts.present.map((c) => ({ id: c.id, name: c.name })),
    result: {
      speech: opts.result.speech,
      action: opts.result.action,
      ...(opts.result.proposals ? { proposals: opts.result.proposals } : {}),
    },
    fired: opts.fired,
    ...(opts.turnBeleg ? { turnBeleg: opts.turnBeleg } : {}),
    ...(opts.formulierungsBeleg ? { formulierungsBeleg: opts.formulierungsBeleg } : {}),
    ...(typeof opts.recallCount === "number" ? { recallCount: opts.recallCount } : {}),
    ...(Array.isArray(opts.contradictions) && opts.contradictions.length ? { contradictions: opts.contradictions } : {}),
  });
  const stored = written.session;
  const sid = String(stored.id ?? opts.session.id);
  const read = await readBack(sid);
  await liveTrace("READER", traceId, { reader: "GET", record_ids: factIds(read.session || stored) });
  await liveTrace("OUTPUT", traceId, { speaker: opts.speaker.name, text: String(opts.result.speech || "").slice(0, 200) });
  await liveTrace("TURN_END", traceId, { status: read.ok ? "PASS" : "TEIL" });
  const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return { session: merged, trace: kernelTrace("POST /api/kernel/commit", stored, merged, read, traceId) };
}

export async function kernelGod(opts: {
  session: Session;
  text: string;
  scope: string;
  targetId?: string;
  otherId?: string;
  szenenuebergang?: string;
}): Promise<{ session: Session; trace: KernelTrace }> {
  const traceId = newTraceId("kg");
  await liveTrace("TURN_START", traceId, { user_id: opts.session.userId, session_id: opts.session.id, authority: "god" });
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/god" });
  const written = await apiKernelGod({
    session: opts.session,
    actorUserId: opts.session.userId,
    trace_id: traceId,
    text: opts.text,
    scope: opts.scope,
    targetId: opts.targetId,
    otherId: opts.otherId,
    szenenuebergang: opts.szenenuebergang,
  });
  const stored = written.session;
  const sid = String(stored.id ?? opts.session.id);
  const read = await readBack(sid);
  await liveTrace("READER", traceId, { reader: "GET", record_ids: factIds(read.session || stored) });
  await liveTrace("OUTPUT", traceId, { speaker: "god", text: String(opts.text || "").slice(0, 200) });
  const applied = ((written as { applied?: Array<{ applied?: boolean }> }).applied || []);
  const lastGod = ((read.session || stored) as { godFacts?: Array<{ applied?: boolean }> }).godFacts?.at(-1);
  const haveEffect = applied.length ? applied.some((x) => x.applied === true) : lastGod?.applied === true;
  const partial = applied.some((x) => x.applied !== true) || Boolean((written as { unclear?: unknown[] }).unclear?.length);
  const semanticStatus = !haveEffect ? "REJECT" : partial ? "TEIL" : "PASS";
  await liveTrace("TURN_END", traceId, { status: !read.ok ? "TEIL" : semanticStatus });
  const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return {
    session: merged,
    trace: kernelTrace("POST /api/kernel/god", stored, merged, read, traceId),
    applied: (written as { applied?: unknown[] }).applied || [],
    unclear: (written as { unclear?: unknown[] }).unclear || [],
  };
}

export async function kernelRegie(opts: {
  session: Session;
  world: World;
  text: string;
  targetId?: string;
  actorId?: string;
  present?: StammCharacter[];
  szenenuebergang?: string;
  directAction?: boolean;
}): Promise<{ session: Session; trace: KernelTrace }> {
  const traceId = newTraceId("kr");
  await liveTrace("TURN_START", traceId, { user_id: opts.session.userId, session_id: opts.session.id, authority: "regie" });
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/regie" });
  const relocates = /\b(geht\s+(?:zur|zum|in|nach)|betritt|wechselt nach|szene(?:ort)?\s*(?:ist|:))\b/i.test(opts.text);
  const place = relocates
    ? (opts.world.places || []).find((p) => p.name && opts.text.toLowerCase().includes(p.name.toLowerCase()))
    : undefined;
  const present = (opts.present || []).map((c) => ({ id: c.id, name: c.name, aliases: c.aliases }));
  const actorId = opts.actorId && opts.actorId !== "regie" ? opts.actorId : undefined;
  const written = await apiKernelRegie({
    session: opts.session,
    world: opts.world,
    actorUserId: opts.session.userId,
    trace_id: traceId,
    text: opts.text,
    targetId: opts.targetId,
    placeName: place?.name,
    actorId,
    present,
    directAction: opts.directAction === true,
    szenenuebergang: opts.szenenuebergang,
  });
  const stored = written.session;
  const sid = String(stored.id ?? opts.session.id);
  const read = await readBack(sid);
  await liveTrace("READER", traceId, { reader: "GET", record_ids: factIds(read.session || stored) });
  await liveTrace("OUTPUT", traceId, { speaker: "regie", text: String(opts.text || "").slice(0, 200) });
  const semanticStatus = String((written as { effect_verdict?: string }).effect_verdict || "UNVERIFIED");
  await liveTrace("TURN_END", traceId, { status: !read.ok ? "TEIL" : semanticStatus });
  const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return { session: merged, trace: kernelTrace("POST /api/kernel/regie", stored, merged, read, traceId) };
}

export async function kernelPuppet(opts: {
  session: Session;
  figure: StammCharacter;
  text: string;
  /** V92 Paket 16: the operator's answers to the server's identity clarification of THIS input */
  klaerungen?: KlaerungAntwort[];
}): Promise<{ session: Session; trace: KernelTrace }> {
  const traceId = newTraceId("kp");
  await liveTrace("TURN_START", traceId, { user_id: opts.session.userId, session_id: opts.session.id, authority: "puppet" });
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/puppet" });
  const split = splitPuppet(opts.text, opts.figure);
  const written = await apiKernelPuppet({
    session: opts.session,
    actorUserId: opts.session.userId,
    trace_id: traceId,
    figure: { id: opts.figure.id, name: opts.figure.name },
    // V65J (AMASTER §23/§24.2/§24.6): the server reads the RAW text like an avatar input
    // (planner components, body-effect reading). The local split stays only as the
    // fallback without a semantic reading; its verb list never decides a body effect.
    text: opts.text,
    speech: split.speech,
    action: split.action ?? null,
    ...(opts.klaerungen?.length ? { klaerungen: opts.klaerungen } : {}),
  });
  const stored = written.session;
  const sid = String(stored.id ?? opts.session.id);
  const read = await readBack(sid);
  await liveTrace("READER", traceId, { reader: "GET", record_ids: factIds(read.session || stored) });
  await liveTrace("OUTPUT", traceId, { speaker: opts.figure.name, text: String(opts.text || "").slice(0, 200) });
  await liveTrace("TURN_END", traceId, { status: read.ok ? "PASS" : "TEIL" });
  const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return { session: merged, trace: kernelTrace("POST /api/kernel/puppet", stored, merged, read, traceId) };
}

async function kernelOwnerWrite(
  writePath: string,
  session: Session,
  authority: string,
  endpoint: string,
  call: () => Promise<{ ok: boolean; session: Record<string, unknown> }>,
  output: { speaker: string; text: string },
): Promise<{ session: Session; trace: KernelTrace }> {
  const traceId = newTraceId("kw");
  await liveTrace("TURN_START", traceId, { user_id: session.userId, session_id: session.id, authority });
  await liveTrace("UI_REQUEST", traceId, { endpoint });
  const written = await call();
  const stored = written.session;
  const sid = String(stored.id ?? session.id);
  const read = await readBack(sid);
  await liveTrace("READER", traceId, { reader: "GET", record_ids: factIds(read.session || stored) });
  await liveTrace("OUTPUT", traceId, { speaker: output.speaker, text: output.text.slice(0, 200) });
  await liveTrace("TURN_END", traceId, { status: read.ok ? "PASS" : "TEIL" });
  const merged = mergeKernelSession(session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return { session: merged, trace: kernelTrace(writePath, stored, merged, read, traceId) };
}

export async function kernelMove(opts: {
  session: Session;
  world: World;
  placeId: string;
  moverId: string;
}): Promise<{ session: Session; trace: KernelTrace }> {
  return kernelOwnerWrite(
    "POST /api/kernel/move",
    opts.session,
    "avatar",
    "/api/kernel/move",
    () =>
      apiKernelMove({
        session: opts.session,
        actorUserId: opts.session.userId,
        world: opts.world,
        placeId: opts.placeId,
        moverId: opts.moverId,
      }),
    { speaker: "move", text: opts.placeId },
  );
}

// Presence is a scene control, not a chat turn. Serialize consecutive taps so
// the canonical SQL readback for one button cannot overwrite a newer selection.
// Do not send a full browser session or five turn-trace HTTP requests for a
// single presence toggle; the backend already logs its UI_REQUEST/SQLITE_COMMIT.
let presenceWriteTail: Promise<void> = Promise.resolve();

export function kernelPresence(opts: {
  session: Session;
  characterId: string;
}): Promise<{ session: Session; trace: KernelTrace }> {
  const operation = presenceWriteTail.then(async () => {
    const traceId = newTraceId("kps");
    const written = await apiKernelPresence({
      sessionId: opts.session.id,
      actorUserId: opts.session.userId,
      characterId: opts.characterId,
      trace_id: traceId,
    });
    const stored = written.session;
    const read = await readBack(opts.session.id);
    const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
    return { session: merged, trace: kernelTrace("POST /api/kernel/presence", stored, merged, read, traceId) };
  });
  presenceWriteTail = operation.then(() => undefined, () => undefined);
  return operation;
}

export async function kernelFate(opts: {
  session: Session;
  enabled?: boolean;
  beat?: string;
  pressure?: number;
  seedId?: string;
}): Promise<{ session: Session; trace: KernelTrace }> {
  return kernelOwnerWrite(
    "POST /api/kernel/fate",
    opts.session,
    "fate",
    "/api/kernel/fate",
    () =>
      apiKernelFate({
        session: opts.session,
        actorUserId: opts.session.userId,
        enabled: opts.enabled,
        beat: opts.beat,
        pressure: opts.pressure,
        seedId: opts.seedId,
      }),
    { speaker: "fate", text: String(opts.enabled ?? opts.beat ?? "") },
  );
}

export async function kernelAutochatGate(opts: {
  session: Session;
  remaining: number;
  userDecision?: string;
  stimulus?: string;
}): Promise<{ stop: boolean; reason: string | null; speakerId?: string; remaining: number }> {
  const gate = await apiKernelAutochatGate({
    session: opts.session,
    actorUserId: opts.session.userId,
    remaining: opts.remaining,
    user_decision: opts.userDecision,
    stimulus: opts.stimulus,
  });
  return {
    stop: Boolean(gate.stop),
    reason: gate.reason ?? null,
    speakerId: gate.speakerId,
    remaining: Number(gate.remaining ?? opts.remaining),
  };
}

export async function kernelPerception(opts: {
  session: Session;
  kind: "hearsIds" | "seesIds";
  ids?: string[];
  explicit?: boolean;
}): Promise<{ session: Session; trace: KernelTrace }> {
  const traceId = newTraceId("kperception");
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/perception", kind: opts.kind });
  const written = await apiKernelPerception({
    sessionId: opts.session.id,
    kind: opts.kind,
    ids: opts.ids ?? [],
    explicit: opts.explicit !== false,
    trace_id: traceId,
  });
  const stored = written.session;
  const read = await readBack(opts.session.id);
  const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return { session: merged, trace: kernelTrace("POST /api/kernel/perception", stored, merged, read, traceId) };
}

export async function kernelReset(opts: {
  session: Session;
  kind: "chat" | "runtime" | "memory" | "uploads";
}): Promise<{ session: Session; trace: KernelTrace }> {
  const traceId = newTraceId("kreset");
  await liveTrace("TURN_START", traceId, { user_id: opts.session.userId, session_id: opts.session.id, authority: "kernel-reset" });
  await liveTrace("UI_REQUEST", traceId, { endpoint: "/api/kernel/reset", kind: opts.kind });
  const written = await apiKernelReset({
    sessionId: opts.session.id,
    kind: opts.kind,
    trace_id: traceId,
  });
  const stored = written.session;
  const sid = String(stored.id ?? opts.session.id);
  const read = await readBack(sid);
  await liveTrace("READER", traceId, { reader: "GET", record_ids: factIds(read.session || stored) });
  await liveTrace("OUTPUT", traceId, { speaker: "kernel-reset", text: opts.kind });
  await liveTrace("TURN_END", traceId, { status: read.ok ? "PASS" : "TEIL" });
  const merged = mergeKernelSession(opts.session, (read.ok && read.session ? read.session : stored) as Record<string, unknown>);
  return { session: merged, trace: kernelTrace("POST /api/kernel/reset", stored, merged, read, traceId) };
}

